from __future__ import annotations
import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional, Protocol

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.goal import Goal
from app.models.habit import Habit
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.orchestrator.triggers import EveningRecapTrigger, MorningBriefTrigger, TaskCheckinTrigger
from app.services.lark_messenger import LarkMessenger

logger = logging.getLogger(__name__)


class _OrchestratorLike(Protocol):
    async def send_proactive(self, user_id: int, trigger, complexity: str = "low") -> Optional[str]: ...


# Window after which task_checkin_1 elapses with no reply → schedule task_checkin_2 (relative to checkin_1 fire time)
CHECKIN_2_DELAY = timedelta(hours=2)
# After task_checkin_2 with no reply → schedule task_checkin_3 (deferred / piggy-back)
CHECKIN_3_DELAY = timedelta(hours=24)


async def _push_to_lark(lark_user_id: str, text: str) -> bool:
    """Indirection so tests can monkeypatch."""
    from app.lark.client import LarkClient
    from app.config import settings
    client = LarkClient(app_id=settings.lark_app_id, app_secret=settings.lark_app_secret)
    return await LarkMessenger(client).push(lark_user_id, text)


async def scan_reminders_once(session: AsyncSession, orchestrator: _OrchestratorLike) -> int:
    """Find pending due reminders, fire each through orchestrator.send_proactive,
    update Reminder.status, and queue follow-ups. Returns count fired this run."""
    now = datetime.now(timezone.utc)
    q = (
        select(Reminder)
        .where(Reminder.status == "pending", Reminder.trigger_time <= now)
        .order_by(Reminder.trigger_time.asc())
        .limit(50)
    )
    rows = (await session.execute(q)).scalars().all()
    fired = 0
    for rem in rows:
        try:
            trigger = await _build_trigger(session, rem)
            if trigger is None:
                rem.status = "cancelled"
                await session.commit()
                continue
            reply = await orchestrator.send_proactive(
                user_id=rem.user_id, trigger=trigger, complexity="low"
            )
            if reply is None:
                rem.status = "failed"
                await session.commit()
                continue
            user = await session.get(User, rem.user_id)
            if user and user.lark_user_id:
                ok = await _push_to_lark(user.lark_user_id, reply)
                if not ok:
                    rem.status = "failed"
                    await session.commit()
                    continue
            rem.status = "sent"
            await session.commit()
            fired += 1

            await _maybe_schedule_next_checkin(session, rem)
        except Exception as e:
            logger.warning("reminder %s failed: %s", rem.id, e)
            rem.status = "failed"
            await session.commit()
    return fired


async def _build_trigger(session: AsyncSession, rem: Reminder):
    if rem.type in ("task_checkin_1", "task_checkin_2", "task_checkin_3"):
        if rem.linked_task_id is None:
            return None
        task = await session.get(Task, rem.linked_task_id)
        if task is None or task.status in ("done", "cancelled"):
            return None
        attempt = {"task_checkin_1": 1, "task_checkin_2": 2, "task_checkin_3": 3}[rem.type]
        return TaskCheckinTrigger(
            task_id=task.id,
            attempt=attempt,
            task_title=task.title,
            deadline=task.deadline.isoformat() if task.deadline else "",
        )
    return None


async def _maybe_schedule_next_checkin(session: AsyncSession, fired: Reminder) -> None:
    """After a checkin_1 fires, queue checkin_2; after checkin_2, queue a deferred checkin_3."""
    if fired.type == "task_checkin_1":
        session.add(Reminder(
            user_id=fired.user_id,
            trigger_time=datetime.now(timezone.utc) + CHECKIN_2_DELAY,
            type="task_checkin_2",
            linked_task_id=fired.linked_task_id,
            status="pending",
            message="",
        ))
        await session.commit()
    elif fired.type == "task_checkin_2":
        session.add(Reminder(
            user_id=fired.user_id,
            trigger_time=datetime.now(timezone.utc) + CHECKIN_3_DELAY,
            type="task_checkin_3",
            linked_task_id=fired.linked_task_id,
            status="deferred",
            message="",
        ))
        await session.commit()


async def expire_stale_checkins(session: AsyncSession) -> int:
    """Find task_checkin_3 rows still deferred past their trigger_time and mark
    the linked task as unknown."""
    now = datetime.now(timezone.utc)
    q = (
        select(Reminder)
        .where(
            Reminder.type == "task_checkin_3",
            Reminder.status == "deferred",
            Reminder.trigger_time <= now,
        )
    )
    rows = (await session.execute(q)).scalars().all()
    expired = 0
    for rem in rows:
        task = await session.get(Task, rem.linked_task_id) if rem.linked_task_id else None
        if task and task.status == "pending":
            task.status = "unknown"
            session.add(Event(
                user_id=rem.user_id,
                conversation_id=None,
                type="task_status_unknown",
                entity_type="task",
                entity_id=task.id,
                payload={"reason": "no response after 3 check-ins"},
            ))
        rem.status = "expired"
        await session.commit()
        expired += 1
    return expired


async def _already_sent_today(session: AsyncSession, user_id: int, event_type: str) -> bool:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    q = (
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.type == event_type,
            Event.created_at >= today_start,
        )
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none() is not None


def _quadrant_priority(q: Optional[str]) -> int:
    return {"urgent_important": 0, "important": 1, "urgent": 2, "neither": 3}.get(q or "neither", 3)


async def send_morning_brief_once(
    session: AsyncSession,
    user_id: int,
    orchestrator: _OrchestratorLike,
) -> bool:
    """Send a morning brief if not already sent today. Returns True if sent."""
    if await _already_sent_today(session, user_id, "morning_brief_sent"):
        return False

    user = await session.get(User, user_id)
    if user is None:
        return False

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tasks_q = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.status.in_(["pending", "in_progress"]),
            (Task.deadline.is_(None)) | ((Task.deadline >= today_start) & (Task.deadline < today_end)),
        )
    )
    tasks = (await session.execute(tasks_q)).scalars().all()

    tasks_sorted = sorted(
        tasks, key=lambda t: (_quadrant_priority(t.quadrant), t.deadline or today_end)
    )
    headline = tasks_sorted[0].title if tasks_sorted else None

    today_plan = []
    for t in tasks_sorted:
        time_str = t.deadline.strftime("%H:%M") if t.deadline else "today"
        today_plan.append({
            "time": time_str,
            "title": t.title,
            "quadrant": t.quadrant,
            "kind": "task",
        })

    habits_q = select(Habit).where(Habit.user_id == user_id, Habit.active == True)
    habits = (await session.execute(habits_q)).scalars().all()
    habits_today = [{"id": h.id, "title": h.title, "frequency": h.frequency_type} for h in habits]

    goals_q = select(Goal).where(Goal.user_id == user_id, Goal.status == "active").limit(5)
    goals = (await session.execute(goals_q)).scalars().all()
    active_goals_brief = [
        {"title": g.title, "progress": f"{g.current_value}/{g.target_value} {g.unit}"}
        for g in goals
    ]

    trigger = MorningBriefTrigger(
        date=date_type.today().isoformat(),
        today_plan=today_plan,
        headline_task=headline,
        habits_today=habits_today,
        active_goals_brief=active_goals_brief,
    )

    reply = await orchestrator.send_proactive(user_id=user_id, trigger=trigger, complexity="low")
    if reply is None:
        return False
    if user.lark_user_id:
        await _push_to_lark(user.lark_user_id, reply)
    return True


async def send_evening_recap_once(
    session: AsyncSession,
    user_id: int,
    orchestrator: _OrchestratorLike,
) -> bool:
    if await _already_sent_today(session, user_id, "evening_recap_sent"):
        return False
    user = await session.get(User, user_id)
    if user is None:
        return False

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    events_q = (
        select(Event)
        .where(Event.user_id == user_id, Event.created_at >= today_start, Event.created_at < today_end)
        .order_by(Event.id)
    )
    events = (await session.execute(events_q)).scalars().all()

    tasks_completed = []
    tasks_missed_local: list[dict] = []
    habits_done = []
    user_feedback = []
    for e in events:
        if e.type == "task_completed":
            tasks_completed.append({"id": e.entity_id, "payload": e.payload})
        elif e.type == "task_status_unknown":
            tasks_missed_local.append({"id": e.entity_id, "payload": e.payload})
        elif e.type == "habit_completed":
            habits_done.append({"id": e.entity_id, "payload": e.payload})
        elif e.type == "feedback_recorded":
            user_feedback.append(e.payload)

    pending_overdue_q = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.status == "pending",
            Task.deadline.is_not(None),
            Task.deadline < datetime.now(timezone.utc),
        )
    )
    overdue = (await session.execute(pending_overdue_q)).scalars().all()
    tasks_missed_local.extend(
        [{"id": t.id, "title": t.title, "deadline": t.deadline.isoformat()} for t in overdue]
    )

    habits_active = (await session.execute(
        select(Habit).where(Habit.user_id == user_id, Habit.active == True)
    )).scalars().all()
    done_ids = {h.get("id") for h in habits_done if isinstance(h.get("id"), int)}
    habits_missed = [
        {"id": h.id, "title": h.title} for h in habits_active if h.id not in done_ids
    ]

    goals_touched: list[dict] = []
    for t in (await session.execute(
        select(Task).where(Task.user_id == user_id, Task.status == "done", Task.goal_id.is_not(None))
    )).scalars().all():
        if t.goal_id and not any(g["id"] == t.goal_id for g in goals_touched):
            goal = await session.get(Goal, t.goal_id)
            if goal:
                goals_touched.append({"id": goal.id, "title": goal.title})

    week_start = today_start - timedelta(days=7)
    week_done = await session.execute(
        select(func.count(Event.id))
        .where(Event.user_id == user_id, Event.type == "task_completed",
               Event.created_at >= week_start)
    )
    week_done_n = week_done.scalar() or 0
    week_created = await session.execute(
        select(func.count(Event.id))
        .where(Event.user_id == user_id, Event.type == "task_created",
               Event.created_at >= week_start)
    )
    week_created_n = max(week_created.scalar() or 0, 1)
    recent_pattern = {"avg_completion_rate": round(week_done_n / week_created_n, 2)}

    trigger = EveningRecapTrigger(
        date=date_type.today().isoformat(),
        tasks_completed=tasks_completed,
        tasks_missed=tasks_missed_local,
        habits_done=habits_done,
        habits_missed=habits_missed,
        goals_touched=goals_touched,
        recent_pattern=recent_pattern,
        user_feedback_today=user_feedback,
    )

    reply = await orchestrator.send_proactive(user_id=user_id, trigger=trigger, complexity="high")
    if reply is None:
        return False
    if user.lark_user_id:
        await _push_to_lark(user.lark_user_id, reply)
    return True


async def orchestrate_daily_jobs_once(
    session: AsyncSession,
    orchestrator: _OrchestratorLike,
) -> dict:
    """Scan all users; for each, decide if their morning brief or evening recap
    should fire this hour and call the relevant job inline."""
    now_utc = datetime.now(timezone.utc)
    users = (await session.execute(select(User))).scalars().all()
    counts = {"morning": 0, "evening": 0}
    for u in users:
        prefs = u.preferences or {}
        profile = (prefs.get("profile") or {})
        tz_name = profile.get("timezone") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        now_local = now_utc.astimezone(tz)

        wake_str = profile.get("wake_up")
        sleep_str = profile.get("sleep_time")

        if wake_str:
            try:
                wh, wm = map(int, wake_str.split(":"))
                morning_local = now_local.replace(hour=wh, minute=wm, second=0, microsecond=0) + timedelta(minutes=30)
                if morning_local.hour == now_local.hour:
                    if await send_morning_brief_once(session, user_id=u.id, orchestrator=orchestrator):
                        counts["morning"] += 1
            except ValueError:
                pass

        if sleep_str:
            try:
                sh, sm = map(int, sleep_str.split(":"))
                evening_local = now_local.replace(hour=sh, minute=sm, second=0, microsecond=0) - timedelta(hours=1)
                if evening_local.hour == now_local.hour:
                    if await send_evening_recap_once(session, user_id=u.id, orchestrator=orchestrator):
                        counts["evening"] += 1
            except ValueError:
                pass
    return counts


async def _build_orchestrator(session):
    from app.llm.router import LLMRouter
    from app.orchestrator.conversation import ConversationOrchestrator
    return ConversationOrchestrator(session=session, llm=LLMRouter())


async def run_scan_reminders() -> None:
    """APScheduler entry point. Opens its own DB session."""
    from app.database import async_session_factory
    async with async_session_factory() as session:
        orch = await _build_orchestrator(session)
        await scan_reminders_once(session, orchestrator=orch)


async def run_orchestrate_daily() -> None:
    from app.database import async_session_factory
    async with async_session_factory() as session:
        orch = await _build_orchestrator(session)
        await orchestrate_daily_jobs_once(session, orchestrator=orch)


async def run_expire_stale_checkins() -> None:
    from app.database import async_session_factory
    async with async_session_factory() as session:
        await expire_stale_checkins(session)


async def run_memory_consolidation() -> None:
    """Nightly: for each user, consolidate patterns + decay confidences."""
    from app.database import async_session_factory
    from app.memory.confidence import decay_pattern_confidence
    from app.memory.consolidation import consolidate_patterns

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            try:
                await consolidate_patterns(session, u.id)
                await decay_pattern_confidence(session, u.id)
            except Exception as e:
                logger.warning("memory consolidation failed for user %s: %s", u.id, e)
