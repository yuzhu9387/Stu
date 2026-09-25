"""Authenticated household kitchen workspace API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.kitchen.contracts import KitchenCommand
from recipe_agent.domain.kitchen.engine import KitchenError
from recipe_agent.domain.kitchen.repository import KitchenRepository
from recipe_agent.infrastructure.jobs.kitchen import KitchenGenerationJob

router = APIRouter(prefix="/kitchen", tags=["kitchen"])


def get_repository(request: Request) -> KitchenRepository:
    settings = getattr(request.app.state, "settings", None)
    return KitchenRepository(
        request.app.state.session_factory,
        relational_read=bool(getattr(settings, "kitchen_relational_read", False)),
    )


@router.get("")
async def get_kitchen(request: Request, scope: ScopeDependency) -> dict[str, Any]:
    return await get_repository(request).get(scope)


@router.post("/commands")
async def kitchen_command(
    command: KitchenCommand, request: Request, scope: ScopeDependency
) -> dict[str, Any]:
    try:
        return await get_repository(request).command(scope, command.model_dump(mode="json"))
    except KitchenError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


def job_json(job: KitchenGenerationJob) -> dict[str, Any]:
    return {
        "weekStart": job.week_start,
        "status": job.status,
        "attempts": job.attempts,
        "error": job.error,
        "nextAttemptAt": job.next_attempt_at.isoformat() if job.next_attempt_at else None,
    }


@router.get("/generation-jobs")
async def generation_jobs(request: Request, scope: ScopeDependency) -> dict[str, Any]:
    from sqlalchemy import select

    async with request.app.state.session_factory() as session:
        jobs = await session.scalars(
            select(KitchenGenerationJob)
            .where(KitchenGenerationJob.household_id == scope.household_id)
            .order_by(KitchenGenerationJob.week_start.desc())
            .limit(52)
        )
        return {"jobs": [job_json(job) for job in jobs]}


@router.post("/generation-jobs/{week_start}/retry")
async def retry_generation(
    week_start: str, request: Request, scope: ScopeDependency
) -> dict[str, Any]:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from recipe_agent.domain.kitchen.scheduling import validate_week

    try:
        validate_week(week_start)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    state = await get_repository(request).get(scope)
    if any(plan["weekStart"] == week_start for plan in state["plans"]):
        raise HTTPException(409, "A plan already exists for this week; existing work is preserved")
    async with request.app.state.session_factory() as session, session.begin():
        job = await session.scalar(
            select(KitchenGenerationJob)
            .where(
                KitchenGenerationJob.household_id == scope.household_id,
                KitchenGenerationJob.week_start == week_start,
            )
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "Generation job not found")
        # SQLite returns naive UTC while PostgreSQL preserves the timezone.
        lease = job.lease_until
        if lease is not None and lease.tzinfo is None:
            lease = lease.replace(tzinfo=UTC)
        if job.status == "running" and lease and lease > datetime.now(UTC):
            raise HTTPException(409, "Generation is already running")
        job.status, job.attempts = "pending", 0
        job.error = job.lease_until = job.next_attempt_at = None
        return {"message": "Retry queued for the application worker", "job": job_json(job)}
