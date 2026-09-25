"""Stu's AI work — a chat turn or a week's draft — as a stored task.

The request that starts the work returns at once. The work runs on the server
and its outcome is stored, so neither a refresh nor a page switch stops it or
loses it: the page asks for the latest task and continues from there. A chat
turn's message joins the conversation immediately; Stu's answer joins it when
it is ready, and its proposal waits on the task until it is applied, kept or
superseded by the next message.

A task whose server went away mid-run keeps a lease; once the lease lapses it
reads as interrupted rather than running forever.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Coroutine
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.ai import AIUnavailable, ChatRequest, GenerateRequest, KitchenAI
from recipe_agent.domain.kitchen.engine import KitchenError
from recipe_agent.domain.kitchen.fulfillment import (
    FulfillmentRequest,
    generate_fulfillment,
    inputs_hash,
)
from recipe_agent.domain.kitchen.scheduling import validate_week
from recipe_agent.infrastructure.db.base import Base

logger = logging.getLogger(__name__)

# A chat turn that redoes the week runs the week generator, so it may take as long.
# Covers two generation attempts at the configurable maximum (10 minutes each),
# plus a possible clarification check. Navigation never expires a live task.
LEASES = {
    "chat": timedelta(minutes=30),
    "generate": timedelta(minutes=30),
    "fulfillment": timedelta(minutes=30),
}
INTERRUPTED = "Stu was interrupted before finishing. Please try again."
# Keeps running work referenced until it finishes; asyncio holds tasks weakly.
_RUNNING: set[asyncio.Task[None]] = set()


class KitchenAITask(Base):
    __tablename__ = "kitchen_ai_tasks"
    __table_args__ = (Index("ix_kitchen_ai_tasks_lookup", "household_id", "kind", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    week_start: Mapped[str] = mapped_column(String(10), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String(120))
    # running → done | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # What became of a finished task's outcome: open until the household
    # applies or keeps it, or a newer message supersedes it.
    resolution: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime) -> datetime:
    # SQLite returns naive UTC while PostgreSQL keeps the zone.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def plan_fingerprint(plan: dict[str, Any]) -> str:
    """What a proposal was made against: the plan's meals and prep."""
    body = json.dumps(
        {"meals": plan["meals"], "prep": plan["prep"]}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(body.encode()).hexdigest()


def task_json(task: KitchenAITask, now: datetime) -> dict[str, Any]:
    result = {key: value for key, value in (task.result or {}).items() if key != "base"}
    return {
        "id": str(task.id),
        "kind": task.kind,
        "status": task.status,
        "resolution": task.resolution,
        "planId": task.plan_id,
        "weekStart": task.week_start,
        "message": task.request.get("message") or task.request.get("prompt") or "",
        "answering": bool(task.request.get("answeringClarification")),
        "result": result or None,
        "error": "Stu couldn't build the lists. Please try again."
        if task.error and "validation error" in task.error
        else task.error,
        "createdAt": _aware(task.created_at).isoformat(),
        # The page measures elapsed time against the server's clock.
        "now": now.isoformat(),
    }


async def drain() -> None:
    """Wait for background work started in this process (tests, shutdown)."""
    while _RUNNING:
        await asyncio.gather(*list(_RUNNING), return_exceptions=True)


class KitchenAITasks:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], ai: KitchenAI) -> None:
        self.sessions, self.ai = sessions, ai
        self.repository = ai.repository

    # ── starting ────────────────────────────────────────────────────────────
    async def start_chat(self, scope: HouseholdScope, request: ChatRequest) -> dict[str, Any]:
        state = await self.repository.get(scope)
        if state["revision"] != request.expectedRevision:
            raise KitchenError("Workspace changed; reload before asking Stu", 409)
        plan = next((p for p in state["plans"] if p["id"] == request.planId), None)
        if plan is None:
            raise ValueError("Plan not found in this household")
        if not set(request.mealIds) <= {m["id"] for m in plan["meals"]}:
            raise ValueError("Referenced meal is not in this plan")
        now = datetime.now(UTC)
        if await self._running(scope, "chat", now, plan_id=request.planId):
            raise KitchenError("Stu is still answering your last message", 409)
        # The server remembers that the next turn answers an open question;
        # a refresh or a stale client must not silently narrow it to "weekend".
        previous = await self.latest(scope, "chat", plan_id=request.planId)
        if (
            previous
            and previous["resolution"] == "open"
            and previous["status"] == "done"
            and (previous.get("result") or {}).get("needsClarification")
            and not request.mealIds
        ):
            request = request.model_copy(update={"answeringClarification": True})
        recorded = await self.repository.command(
            scope,
            {
                "type": "plan.chat",
                "payload": {
                    "planId": request.planId,
                    "messages": [
                        {
                            "id": str(uuid4()),
                            "role": "user",
                            "text": request.message,
                            "mealIds": request.mealIds,
                        }
                    ],
                },
                "expectedRevision": request.expectedRevision,
                "operationId": str(uuid4()),
            },
        )
        async with self.sessions() as session, session.begin():
            # A new message supersedes whatever Stu proposed before it.
            await session.execute(
                update(KitchenAITask)
                .where(
                    KitchenAITask.household_id == scope.household_id,
                    KitchenAITask.kind == "chat",
                    KitchenAITask.plan_id == request.planId,
                    KitchenAITask.resolution == "open",
                )
                .values(resolution="superseded", updated_at=now)
            )
            task = self._new(scope, "chat", plan["weekStart"], request.planId, request, now)
            session.add(task)
        self._spawn(self._run_chat(task.id, scope, request))
        return {"task": task_json(task, now), "state": recorded["state"]}

    async def start_fulfillment(
        self, scope: HouseholdScope, request: FulfillmentRequest
    ) -> dict[str, Any]:
        state = await self.repository.get(scope)
        if state["revision"] != request.expectedRevision:
            raise KitchenError("Workspace changed; reload before confirming", 409)
        plan = next((p for p in state["plans"] if p["id"] == request.planId), None)
        if plan is None or plan["status"] != "draft":
            raise ValueError("Choose a draft to confirm")
        now = datetime.now(UTC)
        running = await self._running(scope, "fulfillment", now, plan_id=plan["id"])
        if running is not None:
            return {"task": task_json(running, now)}
        task = self._new(scope, "fulfillment", plan["weekStart"], plan["id"], request, now)
        async with self.sessions() as session, session.begin():
            session.add(task)
        self._spawn(self._run_fulfillment(task.id, scope, state, plan))
        return {"task": task_json(task, now)}

    async def _run_fulfillment(
        self, task_id: UUID, scope: HouseholdScope, state: dict[str, Any], plan: dict[str, Any]
    ) -> None:
        try:
            fingerprint = inputs_hash(state, plan)
            output = await generate_fulfillment(self.ai.provider, state, plan)
            for attempt in range(3):
                latest = await self.repository.get(scope)
                try:
                    await self.repository.command(
                        scope,
                        {
                            "type": "plan.fulfill",
                            "payload": {
                                "id": plan["id"],
                                "inputHash": fingerprint,
                                "output": output,
                            },
                            "expectedRevision": latest["revision"],
                            "operationId": str(task_id),
                        },
                    )
                    break
                except KitchenError as exc:
                    if exc.status_code != 409 or attempt == 2:
                        raise
            await self._finish(task_id, result={"planId": plan["id"]})
        except (AIUnavailable, KitchenError) as exc:
            await self._finish(task_id, error=str(exc)[:1000])
        except ValueError:
            logger.exception("invalid kitchen fulfillment result")
            await self._finish(task_id, error="Stu couldn't build the lists. Please try again.")
        except Exception:
            logger.exception("kitchen fulfillment task failed")
            await self._finish(
                task_id, error="Stu couldn't prepare the shopping and prep lists. Please try again."
            )

    async def start_generate(
        self, scope: HouseholdScope, request: GenerateRequest
    ) -> dict[str, Any]:
        validate_week(request.weekStart)
        state = await self.repository.get(scope)
        if state["revision"] != request.expectedRevision:
            raise KitchenError("Workspace changed; reload before generating", 409)
        if any(
            p["weekStart"] == request.weekStart and p["status"] == "confirmed"
            for p in state["plans"]
        ):
            raise ValueError(
                "This week is already confirmed. Edit or chat with that plan "
                "to preserve its locked and executed meals."
            )
        now = datetime.now(UTC)
        running = await self._running(scope, "generate", now, week_start=request.weekStart)
        if running is not None:
            return {"task": task_json(running, now)}
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KitchenAITask)
                .where(
                    KitchenAITask.household_id == scope.household_id,
                    KitchenAITask.kind == "generate",
                    KitchenAITask.week_start == request.weekStart,
                    KitchenAITask.resolution == "open",
                )
                .values(resolution="superseded", updated_at=now)
            )
            task = self._new(scope, "generate", request.weekStart, None, request, now)
            session.add(task)
        self._spawn(self._run_generate(task.id, scope, request))
        return {"task": task_json(task, now)}

    # ── reading ─────────────────────────────────────────────────────────────
    async def latest(
        self,
        scope: HouseholdScope,
        kind: str,
        *,
        plan_id: str | None = None,
        week_start: str | None = None,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        async with self.sessions() as session:
            query = select(KitchenAITask).where(
                KitchenAITask.household_id == scope.household_id, KitchenAITask.kind == kind
            )
            if plan_id is not None:
                query = query.where(KitchenAITask.plan_id == plan_id)
            if week_start is not None:
                query = query.where(KitchenAITask.week_start == week_start)
            task = await session.scalar(query.order_by(KitchenAITask.created_at.desc()).limit(1))
        if task is None:
            return None
        return task_json(await self._expire(task, now), now)

    async def get(self, scope: HouseholdScope, task_id: UUID) -> dict[str, Any]:
        now = datetime.now(UTC)
        task = await self._load(scope, task_id)
        return task_json(await self._expire(task, now), now)

    # ── resolving ───────────────────────────────────────────────────────────
    async def apply(self, scope: HouseholdScope, task_id: UUID) -> dict[str, Any]:
        """Save a chat proposal into its plan, if the plan is as Stu saw it."""
        task = await self._load(scope, task_id)
        if task.kind != "chat" or task.status != "done" or not task.result:
            raise KitchenError("There is nothing to apply from this answer", 409)
        if task.resolution != "open":
            raise KitchenError("This suggestion was already handled", 409)
        result = task.result
        if not result.get("meals"):
            raise KitchenError("This answer has no changes to apply", 409)
        state = await self.repository.get(scope)
        plan = next((p for p in state["plans"] if p["id"] == task.plan_id), None)
        if plan is None or plan_fingerprint(plan) != result.get("base"):
            raise KitchenError(
                "This plan changed after Stu's suggestion. Ask again before applying.", 409
            )
        draft = deepcopy(plan)
        if plan["status"] == "confirmed":
            draft.update(
                id=str(uuid4()), status="draft", basePlanId=plan["id"], baseVersion=plan["version"]
            )
        changes = {meal["id"]: meal for meal in result["meals"]}
        draft["meals"] = [changes.get(meal["id"], meal) for meal in plan["meals"]]
        if result.get("prep") is not None:
            draft["prep"] = result["prep"]
        saved = await self.repository.command(
            scope,
            {
                "type": "plan.save",
                "payload": {"plan": draft, "recipes": result.get("recipes", [])},
                "expectedRevision": state["revision"],
                "operationId": str(uuid4()),
            },
        )
        await self._resolve(scope, task_id, "applied")
        return {**saved, "planId": draft["id"]}

    async def dismiss(self, scope: HouseholdScope, task_id: UUID) -> dict[str, Any]:
        await self._load(scope, task_id)
        await self._resolve(scope, task_id, "dismissed")
        return await self.get(scope, task_id)

    # ── running ─────────────────────────────────────────────────────────────
    async def _run_chat(self, task_id: UUID, scope: HouseholdScope, request: ChatRequest) -> None:
        try:
            state = await self.repository.get(scope)
            plan = next((p for p in state["plans"] if p["id"] == request.planId), None)
            if plan is None:
                raise ValueError("This plan no longer exists")
            result = await self.ai.propose(state, request)
            result["base"] = plan_fingerprint(plan)
            await self._say(scope, request.planId, result)
            await self._finish(task_id, result=result)
        except (AIUnavailable, KitchenError, ValueError) as exc:
            await self._finish(task_id, error=str(exc)[:1000])
        except Exception:
            logger.exception("kitchen chat task failed")
            await self._finish(task_id, error="Stu couldn't finish this answer. Please try again.")

    async def _run_generate(
        self, task_id: UUID, scope: HouseholdScope, request: GenerateRequest
    ) -> None:
        try:
            state = await self.repository.get(scope)
            saved = await self.ai.generate(
                scope,
                request.model_copy(update={"expectedRevision": state["revision"]}),
                rebase=True,
            )
            await self._finish(task_id, result={"planId": saved["planId"]})
        except (AIUnavailable, KitchenError, ValueError) as exc:
            await self._finish(task_id, error=str(exc)[:1000])
        except Exception:
            logger.exception("kitchen generation task failed")
            await self._finish(task_id, error="Stu couldn't finish this draft. Please try again.")

    async def _say(self, scope: HouseholdScope, plan_id: str, result: dict[str, Any]) -> None:
        """Add Stu's reply to the conversation, whatever else changed meanwhile."""
        for attempt in range(3):
            state = await self.repository.get(scope)
            try:
                await self.repository.command(
                    scope,
                    {
                        "type": "plan.chat",
                        "payload": {
                            "planId": plan_id,
                            "messages": [
                                {
                                    "id": str(uuid4()),
                                    "role": "assistant",
                                    "text": result["reply"],
                                    "mealIds": [i for i in result["scope"].split(",") if i],
                                }
                            ],
                        },
                        "expectedRevision": state["revision"],
                        "operationId": str(uuid4()),
                    },
                )
                return
            except KitchenError as exc:
                if exc.status_code != 409 or attempt == 2:
                    raise

    # ── storage ─────────────────────────────────────────────────────────────
    @staticmethod
    def _new(
        scope: HouseholdScope,
        kind: str,
        week_start: str,
        plan_id: str | None,
        request: ChatRequest | GenerateRequest | FulfillmentRequest,
        now: datetime,
    ) -> KitchenAITask:
        return KitchenAITask(
            id=uuid4(),
            household_id=scope.household_id,
            kind=kind,
            week_start=week_start,
            plan_id=plan_id,
            status="running",
            resolution="open",
            request=request.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
            lease_until=now + LEASES[kind],
        )

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        _RUNNING.add(task)
        task.add_done_callback(_RUNNING.discard)

    async def _running(
        self,
        scope: HouseholdScope,
        kind: str,
        now: datetime,
        *,
        plan_id: str | None = None,
        week_start: str | None = None,
    ) -> KitchenAITask | None:
        async with self.sessions() as session:
            query = select(KitchenAITask).where(
                KitchenAITask.household_id == scope.household_id,
                KitchenAITask.kind == kind,
                KitchenAITask.status == "running",
            )
            if plan_id is not None:
                query = query.where(KitchenAITask.plan_id == plan_id)
            if week_start is not None:
                query = query.where(KitchenAITask.week_start == week_start)
            tasks = (await session.scalars(query)).all()
        live = [task for task in tasks if _aware(task.lease_until) > now]
        for task in tasks:
            if task not in live:
                await self._expire(task, now)
        return max(live, key=lambda task: _aware(task.created_at), default=None)

    async def _load(self, scope: HouseholdScope, task_id: UUID) -> KitchenAITask:
        async with self.sessions() as session:
            task = await session.get(KitchenAITask, task_id)
        if task is None or task.household_id != scope.household_id:
            raise KitchenError("Task not found", 404)
        return task

    async def _expire(self, task: KitchenAITask, now: datetime) -> KitchenAITask:
        if task.status != "running" or _aware(task.lease_until) > now:
            return task
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KitchenAITask)
                .where(KitchenAITask.id == task.id, KitchenAITask.status == "running")
                .values(status="failed", error=INTERRUPTED, updated_at=now)
            )
        task.status, task.error = "failed", INTERRUPTED
        return task

    async def _finish(
        self, task_id: UUID, *, result: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KitchenAITask)
                .where(KitchenAITask.id == task_id, KitchenAITask.status == "running")
                .values(
                    status="failed" if error else "done",
                    result=result,
                    error=error,
                    updated_at=datetime.now(UTC),
                )
            )

    async def _resolve(self, scope: HouseholdScope, task_id: UUID, resolution: str) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(KitchenAITask)
                .where(
                    KitchenAITask.id == task_id,
                    KitchenAITask.household_id == scope.household_id,
                    KitchenAITask.resolution == "open",
                )
                .values(resolution=resolution, updated_at=datetime.now(UTC))
            )
