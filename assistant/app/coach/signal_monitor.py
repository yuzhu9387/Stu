from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.task import Task
from app.models.user import User

logger = logging.getLogger(__name__)

DEDUP_HOURS = 24
SILENCE_DAYS = 3
DEFER_COUNT_THRESHOLD = 3


def _as_utc(dt: datetime) -> datetime:
    """Coerce a possibly-naive datetime (as returned by SQLite) to UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _recently_in_coach(session: AsyncSession, user_id: int, hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        select(DialogueSession)
        .where(
            DialogueSession.user_id == user_id,
            DialogueSession.flow_type == "coach",
            DialogueSession.created_at >= cutoff,
        )
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none() is not None


async def _detect_trigger(session: AsyncSession, user_id: int) -> Optional[str]:
    """Returns a trigger-reason string, or None if no signal is hot."""
    now = datetime.now(timezone.utc)

    # Signal A: 3-day silence
    last_user_msg_q = (
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.role == "user")
        .order_by(desc(Conversation.id))
        .limit(1)
    )
    last_user_msg = (await session.execute(last_user_msg_q)).scalar_one_or_none()
    if last_user_msg and (now - _as_utc(last_user_msg.created_at)) > timedelta(days=SILENCE_DAYS):
        days = (now - _as_utc(last_user_msg.created_at)).days
        return f"You haven't said anything in {days} days."

    # Signal B: recent negative feedback within 24h
    recent_feedback_q = (
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.type == "feedback_recorded",
            Event.created_at >= now - timedelta(hours=24),
        )
        .order_by(desc(Event.id))
        .limit(1)
    )
    recent_feedback = (await session.execute(recent_feedback_q)).scalar_one_or_none()
    if recent_feedback and (recent_feedback.payload or {}).get("sentiment") == "negative":
        return "You weren't happy with how things went earlier."

    # Signal C: a single task has been task_updated'd with a deadline change >=3 times
    # and is still pending
    update_events_q = select(Event).where(
        Event.user_id == user_id,
        Event.type == "task_updated",
        Event.entity_type == "task",
    )
    updates = (await session.execute(update_events_q)).scalars().all()
    deferral_counts: dict[int, int] = {}
    for ev in updates:
        payload = ev.payload or {}
        before_deadline = (payload.get("before") or {}).get("deadline")
        after_deadline = (payload.get("after") or {}).get("deadline")
        if before_deadline != after_deadline and after_deadline is not None and ev.entity_id is not None:
            deferral_counts[ev.entity_id] = deferral_counts.get(ev.entity_id, 0) + 1
    over_threshold = sorted(
        [tid for tid, c in deferral_counts.items() if c >= DEFER_COUNT_THRESHOLD]
    )
    for tid in over_threshold:
        task = await session.get(Task, tid)
        if task and task.status == "pending":
            return f"'{task.title}' has been pushed {deferral_counts[tid]} times and is still on your list."

    return None


async def run_coach_signal_check() -> None:
    """Daily: scan all users, fire coach opening trigger if a signal is hot and user
    hasn't been in coach mode recently."""
    from app.database import async_session_factory
    from app.orchestrator.triggers import CoachOpeningTrigger
    from app.scheduler.jobs import _build_orchestrator

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            try:
                if await _recently_in_coach(session, u.id, DEDUP_HOURS):
                    continue
                reason = await _detect_trigger(session, u.id)
                if not reason:
                    continue
                orch = await _build_orchestrator(session)
                await orch.send_proactive(
                    user_id=u.id,
                    trigger=CoachOpeningTrigger(reason=reason),
                    complexity="high",
                )
            except Exception as e:
                logger.warning("coach signal check failed for user %s: %s", u.id, e)
