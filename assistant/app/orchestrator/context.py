from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.retrieval import episodic_recall
from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.goal import Goal
from app.models.habit import Habit
from app.models.task import Task
from app.models.user import User
from app.orchestrator.flows import FieldDef, get_flow
from app.schemas.preferences import Pattern, Profile, UserPreferences


RECENT_TURNS_CAP = 60
YESTERDAY_TAIL = 5
MORNING_HOUR_CUTOFF = 12
OPEN_TASKS_LIMIT = 5
ACTIVE_GOALS_LIMIT = 10
ACTIVE_HABITS_LIMIT = 15


@dataclass
class Context:
    user_id: int
    user_name: str
    profile: Profile
    procedural_patterns: list[Pattern]
    onboarding_status: str
    active_flow: Optional[str]
    flow_filled_fields: dict
    flow_missing_fields: list[FieldDef]
    recent_turns: list[dict]
    open_tasks: list[dict]
    active_goals: list[dict]
    active_habits: list[dict]
    episodic_recall: list[dict]


async def load_context(
    user_id: int,
    session: AsyncSession,
    query_text: str = "",
) -> Context:
    user = await session.get(User, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    prefs = UserPreferences.from_jsonb(user.preferences or {})

    # User-tz aware "today" boundary
    tz_name = (prefs.profile.timezone or "UTC") if prefs.profile else "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(timezone.utc)

    # Active flow lookup
    flow_q = (
        select(DialogueSession)
        .where(DialogueSession.user_id == user_id, DialogueSession.status == "active")
        .order_by(desc(DialogueSession.id))
        .limit(1)
    )
    flow_row = (await session.execute(flow_q)).scalar_one_or_none()
    active_flow_name = flow_row.flow_type if flow_row else None

    flow_filled: dict = {}
    flow_missing: list[FieldDef] = []
    if active_flow_name:
        flow_def = get_flow(active_flow_name)
        if flow_def is not None:
            profile_dict = prefs.profile.model_dump(exclude_none=True)
            flow_filled = {
                f.name: profile_dict[f.name]
                for f in flow_def.required_fields
                if f.name in profile_dict
            }
            flow_missing = flow_def.missing_fields(flow_filled)

    # Today's full conversation (capped at RECENT_TURNS_CAP)
    turns_q = (
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.created_at >= today_start_utc,
        )
        .order_by(desc(Conversation.id))
        .limit(RECENT_TURNS_CAP)
    )
    turns_rows = (await session.execute(turns_q)).scalars().all()
    today_turns = [
        {"role": t.role, "content": t.content, "intent": t.intent}
        for t in reversed(turns_rows)
    ]

    # Optional yesterday tail in the morning if today is sparse
    yesterday_tail: list[dict] = []
    if len(today_turns) < YESTERDAY_TAIL and now_local.hour < MORNING_HOUR_CUTOFF:
        yesterday_end_utc = today_start_utc
        yesterday_start_utc = yesterday_end_utc - timedelta(days=1)
        y_q = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.created_at >= yesterday_start_utc,
                Conversation.created_at < yesterday_end_utc,
            )
            .order_by(desc(Conversation.id))
            .limit(YESTERDAY_TAIL)
        )
        y_rows = (await session.execute(y_q)).scalars().all()
        yesterday_tail = [
            {"role": t.role, "content": t.content, "intent": t.intent}
            for t in reversed(y_rows)
        ]

    recent_turns = yesterday_tail + today_turns

    tasks_q = (
        select(Task)
        .where(Task.user_id == user_id, Task.status.in_(["pending", "in_progress"]))
        .order_by(Task.deadline.asc(), Task.id)
        .limit(OPEN_TASKS_LIMIT)
    )
    tasks_rows = (await session.execute(tasks_q)).scalars().all()
    open_tasks = [
        {"id": t.id, "title": t.title, "status": t.status, "deadline": t.deadline.isoformat() if t.deadline else None}
        for t in tasks_rows
    ]

    goals_q = (
        select(Goal)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.id)
        .limit(ACTIVE_GOALS_LIMIT)
    )
    goals_rows = (await session.execute(goals_q)).scalars().all()
    active_goals = [
        {"id": g.id, "title": g.title, "target_value": g.target_value,
         "current_value": g.current_value, "unit": g.unit,
         "period_end": g.period_end.isoformat() if g.period_end else None}
        for g in goals_rows
    ]

    habits_q = (
        select(Habit)
        .where(Habit.user_id == user_id, Habit.active == True)
        .order_by(Habit.id)
        .limit(ACTIVE_HABITS_LIMIT)
    )
    habits_rows = (await session.execute(habits_q)).scalars().all()
    active_habits = [
        {"id": h.id, "title": h.title, "frequency_type": h.frequency_type,
         "frequency_count": h.frequency_count}
        for h in habits_rows
    ]

    # Cross-day vector recall (only if a query is given)
    episodic_recall_results: list[dict] = []
    if query_text:
        episodic_recall_results = await episodic_recall(session, user_id, query_text)

    return Context(
        user_id=user.id,
        user_name=user.name,
        profile=prefs.profile,
        procedural_patterns=prefs.procedural,
        onboarding_status=prefs.onboarding_status,
        active_flow=active_flow_name,
        flow_filled_fields=flow_filled,
        flow_missing_fields=flow_missing,
        recent_turns=recent_turns,
        open_tasks=open_tasks,
        active_goals=active_goals,
        active_habits=active_habits,
        episodic_recall=episodic_recall_results,
    )
