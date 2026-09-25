"""Durable Friday household generation claims, bounded retry and outage catch-up."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.config import Settings
from recipe_agent.domain.identity.models import Household
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI, Provider
from recipe_agent.domain.kitchen.scheduling import due_week
from recipe_agent.infrastructure.db.base import Base


class KitchenGenerationJob(Base):
    __tablename__ = "kitchen_generation_jobs"
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    week_start: Mapped[str] = mapped_column(String(10), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


async def claim_job(
    session_factory: async_sessionmaker[AsyncSession], household_id: UUID, week: str, now: datetime
) -> int | None:
    async with session_factory() as session, session.begin():
        try:
            async with session.begin_nested():
                session.add(KitchenGenerationJob(household_id=household_id, week_start=week))
                await session.flush()
        except IntegrityError:
            pass
        await session.execute(
            update(KitchenGenerationJob)
            .where(
                KitchenGenerationJob.household_id == household_id,
                KitchenGenerationJob.week_start == week,
                KitchenGenerationJob.status == "running",
                KitchenGenerationJob.attempts >= 3,
                KitchenGenerationJob.lease_until <= now,
            )
            .values(
                status="failed",
                lease_until=None,
                error="Generation worker lease expired after three attempts",
            )
        )
        result = await session.execute(
            update(KitchenGenerationJob)
            .where(
                KitchenGenerationJob.household_id == household_id,
                KitchenGenerationJob.week_start == week,
                KitchenGenerationJob.status.in_(["pending", "retry", "running"]),
                KitchenGenerationJob.attempts < 3,
                or_(
                    KitchenGenerationJob.lease_until.is_(None),
                    KitchenGenerationJob.lease_until <= now,
                ),
                or_(
                    KitchenGenerationJob.next_attempt_at.is_(None),
                    KitchenGenerationJob.next_attempt_at <= now,
                ),
            )
            .values(
                status="running",
                attempts=KitchenGenerationJob.attempts + 1,
                lease_until=now + timedelta(minutes=20),
            )
            .returning(KitchenGenerationJob.attempts)
        )
        return result.scalar_one_or_none()


async def finish_job(
    session_factory: async_sessionmaker[AsyncSession],
    household_id: UUID,
    week: str,
    attempt: int,
    now: datetime,
    error: str | None = None,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(KitchenGenerationJob)
            .where(
                KitchenGenerationJob.household_id == household_id,
                KitchenGenerationJob.week_start == week,
                KitchenGenerationJob.attempts == attempt,
                KitchenGenerationJob.status == "running",
            )
            .values(
                status=("failed" if attempt >= 3 else "retry") if error else "done",
                lease_until=None,
                error=error,
                next_attempt_at=now + timedelta(minutes=5 * 2 ** (attempt - 1)) if error else None,
            )
        )


async def run_due_kitchen_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime | None = None,
    provider: Provider | None = None,
) -> int:
    """Call periodically from the app worker; safe across concurrent worker instances.

    A draft/confirmed plan already present for the target week always wins. Crashes
    after plan persistence are safe: the next attempt finds that plan and marks done.
    """
    from recipe_agent.domain.kitchen.repository import KitchenRepository

    now = now or datetime.now(UTC)
    repository = KitchenRepository(
        session_factory, relational_read=settings.kitchen_relational_read
    )
    ai = KitchenAI(repository, settings, provider)
    async with session_factory() as session:
        households = (await session.execute(select(Household.id, Household.owner_account_id))).all()
    completed = 0
    for household_id, account_id in households:
        scope = HouseholdScope(account_id=account_id, household_id=household_id)
        state = await repository.get(scope)
        week = due_week(now, state["settings"])
        if week is None:
            continue
        attempt = await claim_job(session_factory, household_id, week, now)
        if attempt is None:
            continue
        try:
            # Refresh after claim: an interactive edit during claiming must not be lost.
            state = await repository.get(scope)
            if not any(p["weekStart"] == week for p in state["plans"]):
                await ai.generate(
                    scope,
                    GenerateRequest(
                        weekStart=week,
                        prompt=next(
                            (
                                entry["prompt"]
                                for entry in state.get("weeklyPrompts", [])
                                if entry["weekStart"] == week
                            ),
                            "Prepare next week using enabled household guidance.",
                        ),
                        expectedRevision=state["revision"],
                        operationId=f"friday:{household_id}:{week}",
                    ),
                )
            await finish_job(session_factory, household_id, week, attempt, now)
            completed += 1
        except Exception as exc:
            # Save actionable safe category/message; never persist provider credentials.
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "AI generation failed; check provider availability"
            )
            await finish_job(session_factory, household_id, week, attempt, now, message[:1000])
    return completed
