from __future__ import annotations
import logging
from typing import Literal, Optional

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.router import LLMError, LLMRouter
from app.models.conversation import Conversation
from app.models.event import Event
from app.models.reminder import Reminder
from app.models.task import Task
from app.orchestrator.act import ActionExecutor
from app.orchestrator.actions import ActionType, ParsedAction, StartFlowParams
from app.orchestrator.context import load_context
from app.orchestrator.react import react_or_raise
from app.orchestrator.triggers import (
    CoachOpeningTrigger,
    Trigger,
    WelcomeTrigger,
    synthetic_message_for,
)

logger = logging.getLogger(__name__)


async def _find_piggyback(session: AsyncSession, user_id: int) -> Optional[dict]:
    """Return the oldest deferred task_checkin_3 for the user whose linked task
    is still pending. Returns dict with reminder_id + task info, or None."""
    q = (
        select(Reminder)
        .where(
            Reminder.user_id == user_id,
            Reminder.type == "task_checkin_3",
            Reminder.status == "deferred",
        )
        .order_by(asc(Reminder.trigger_time))
    )
    rows = (await session.execute(q)).scalars().all()
    for rem in rows:
        if rem.linked_task_id is None:
            continue
        task = await session.get(Task, rem.linked_task_id)
        if task is None or task.status in ("done", "cancelled", "unknown"):
            continue
        return {
            "reminder_id": rem.id,
            "task_id": task.id,
            "task_title": task.title,
            "deadline": task.deadline.isoformat() if task.deadline else "",
        }
    return None


async def send_proactive_impl(
    session: AsyncSession,
    llm: LLMRouter,
    user_id: int,
    trigger: Trigger,
    complexity: Literal["low", "high"],
) -> Optional[str]:
    """Outbound proactive message. REACT-only path with optional pre-ACT for Welcome.

    Returns the reply text, or None if generation failed (caller logs and skips push).
    """
    ctx = await load_context(user_id, session)

    if isinstance(trigger, WelcomeTrigger):
        executor = ActionExecutor(session)
        await executor.execute_all(
            user_id=user_id,
            actions=[ParsedAction(ActionType.START_FLOW, StartFlowParams(flow_name="onboarding"))],
            conversation_id=None,
        )
        ctx = await load_context(user_id, session)
        hint = "warmly introduce yourself, then ask the first onboarding question naturally"
    elif isinstance(trigger, CoachOpeningTrigger):
        executor = ActionExecutor(session)
        await executor.execute_all(
            user_id=user_id,
            actions=[ParsedAction(ActionType.START_FLOW, StartFlowParams(flow_name="coach"))],
            conversation_id=None,
        )
        ctx = await load_context(user_id, session)
        hint = "warm, third-party observer; open with one question grounded in the reason"
    else:
        hint = _hint_for(trigger)

    synth = synthetic_message_for(trigger)
    piggyback = await _find_piggyback(session, user_id)
    try:
        reply = await react_or_raise(
            ctx=ctx,
            message=synth,
            action_results=[],
            hint=hint,
            complexity=complexity,
            llm=llm,
            piggyback=piggyback,
        )
    except LLMError as e:
        logger.warning("send_proactive REACT failed: %s", e)
        return None

    session.add(
        Conversation(
            user_id=user_id,
            role="assistant",
            content=reply,
            intent=f"proactive:{trigger.type}",
        )
    )
    session.add(
        Event(
            user_id=user_id,
            conversation_id=None,
            type=f"{trigger.type}_sent",
            entity_type="proactive",
            entity_id=None,
            payload=trigger.model_dump(),
        )
    )
    await session.commit()

    if piggyback is not None:
        rem = await session.get(Reminder, piggyback["reminder_id"])
        if rem is not None:
            rem.status = "sent"
            await session.commit()

    return reply


def _hint_for(trigger: Trigger) -> str:
    return {
        "task_checkin": "gentle friendly check-in; never pressuring",
        "morning_brief": "short greeting + list-style today's plan + close with encouragement",
        "evening_recap": "four short paragraphs: facts → observation → 1-2 suggestions → specific praise",
    }.get(trigger.type, "")
