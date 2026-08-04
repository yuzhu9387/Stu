import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models.event import Event
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User


class _FakeOrchestrator:
    """Captures send_proactive calls without touching LLM."""
    def __init__(self):
        self.calls = []

    async def send_proactive(self, user_id, trigger, complexity="low"):
        self.calls.append({"user_id": user_id, "trigger": trigger, "complexity": complexity})
        return f"sent: {trigger.type}"


async def test_scan_reminders_fires_due_task_checkin(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u1", preferences={})
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="report",
                deadline=datetime.now(timezone.utc) - timedelta(minutes=15), status="pending")
    session.add(task)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(seconds=10),
        type="task_checkin_1",
        linked_task_id=task.id,
        status="pending",
        message="",
    )
    session.add(rem)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    fired = await scan_reminders_once(session, orchestrator=orch)
    assert fired == 1
    assert orch.calls[0]["trigger"].type == "task_checkin"
    assert orch.calls[0]["trigger"].attempt == 1

    await session.refresh(rem)
    assert rem.status == "sent"


async def test_scan_reminders_skips_future(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u2", preferences={})
    session.add(user)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) + timedelta(hours=1),
        type="task_checkin_1",
        linked_task_id=None,
        status="pending",
        message="",
    )
    session.add(rem)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    fired = await scan_reminders_once(session, orchestrator=orch)
    assert fired == 0
    assert orch.calls == []


async def test_scan_reminders_skips_cancelled(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u3", preferences={})
    session.add(user)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        type="task_checkin_1",
        linked_task_id=None,
        status="cancelled",
        message="",
    )
    session.add(rem)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    fired = await scan_reminders_once(session, orchestrator=orch)
    assert fired == 0


async def test_scan_reminders_schedules_checkin_2_after_1(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u4", preferences={})
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="x",
                deadline=datetime.now(timezone.utc) - timedelta(minutes=30), status="pending")
    session.add(task)
    await session.commit()
    rem1 = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(minutes=15),
        type="task_checkin_1",
        linked_task_id=task.id,
        status="pending",
        message="",
    )
    session.add(rem1)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    await scan_reminders_once(session, orchestrator=orch)

    rems = (await session.execute(select(Reminder).order_by(Reminder.id))).scalars().all()
    assert rems[0].status == "sent"
    assert any(r.type == "task_checkin_2" and r.status == "pending" for r in rems)


async def test_expire_unanswered_checkin_3_marks_task_unknown(session):
    user = User(name="A", lark_user_id="sched_u5", preferences={})
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="ghost task",
                deadline=datetime.now(timezone.utc) - timedelta(hours=48), status="pending")
    session.add(task)
    await session.commit()
    rem3 = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=24),
        type="task_checkin_3",
        linked_task_id=task.id,
        status="deferred",
        message="",
    )
    session.add(rem3)
    await session.commit()

    from app.scheduler.jobs import expire_stale_checkins
    expired = await expire_stale_checkins(session)
    assert expired == 1

    await session.refresh(task)
    assert task.status == "unknown"
    await session.refresh(rem3)
    assert rem3.status == "expired"
    events = (await session.execute(select(Event).where(Event.user_id == user.id))).scalars().all()
    assert any(e.type == "task_status_unknown" for e in events)


async def test_morning_brief_gathers_today_and_calls_send_proactive(session, monkeypatch):
    user = User(
        name="A", lark_user_id="sched_morning",
        preferences={"profile": {"wake_up": "07:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()
    today_end = datetime.now(timezone.utc).replace(hour=17, minute=0, second=0, microsecond=0)
    task1 = Task(
        user_id=user.id, title="critical", status="pending",
        quadrant="urgent_important", deadline=today_end,
    )
    session.add(task1)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import send_morning_brief_once
    out = await send_morning_brief_once(session, user_id=user.id, orchestrator=orch)
    assert out is True
    assert len(orch.calls) == 1
    trigger = orch.calls[0]["trigger"]
    assert trigger.type == "morning_brief"
    titles = [item.get("title") for item in trigger.today_plan]
    assert "critical" in titles


async def test_morning_brief_idempotent_in_same_day(session, monkeypatch):
    user = User(
        name="A", lark_user_id="sched_morning_idem",
        preferences={"profile": {"wake_up": "07:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()
    session.add(Event(
        user_id=user.id, conversation_id=None,
        type="morning_brief_sent", entity_type="proactive", entity_id=None,
        payload={},
    ))
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import send_morning_brief_once
    out = await send_morning_brief_once(session, user_id=user.id, orchestrator=orch)
    assert out is False
    assert orch.calls == []


async def test_evening_recap_uses_complexity_high(session, monkeypatch):
    user = User(
        name="A", lark_user_id="sched_evening",
        preferences={"profile": {"sleep_time": "23:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import send_evening_recap_once
    out = await send_evening_recap_once(session, user_id=user.id, orchestrator=orch)
    assert out is True
    assert orch.calls[0]["complexity"] == "high"
    assert orch.calls[0]["trigger"].type == "evening_recap"


async def test_evening_recap_idempotent(session, monkeypatch):
    user = User(
        name="A", lark_user_id="sched_evening_idem",
        preferences={"profile": {"sleep_time": "23:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()
    session.add(Event(
        user_id=user.id, conversation_id=None,
        type="evening_recap_sent", entity_type="proactive", entity_id=None,
        payload={},
    ))
    await session.commit()

    orch = _FakeOrchestrator()
    from app.scheduler.jobs import send_evening_recap_once
    out = await send_evening_recap_once(session, user_id=user.id, orchestrator=orch)
    assert out is False
    assert orch.calls == []


async def test_orchestrate_daily_jobs_picks_users_due_this_hour(session, monkeypatch):
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    wake_due_str = f"{(current_hour - 0):02d}:00"
    wake_other_str = f"{(current_hour + 6) % 24:02d}:00"

    u_due = User(name="due", lark_user_id="ddl_due",
                 preferences={"profile": {"wake_up": wake_due_str, "sleep_time": "23:00"}})
    u_other = User(name="other", lark_user_id="ddl_other",
                   preferences={"profile": {"wake_up": wake_other_str, "sleep_time": "23:00"}})
    session.add(u_due)
    session.add(u_other)
    await session.commit()

    triggered: list[int] = []

    async def fake_morning(session_, user_id, orchestrator):
        triggered.append(user_id)
        return True

    monkeypatch.setattr("app.scheduler.jobs.send_morning_brief_once", fake_morning)

    async def fake_evening(*a, **kw):
        return False
    monkeypatch.setattr("app.scheduler.jobs.send_evening_recap_once", fake_evening)

    from app.scheduler.jobs import orchestrate_daily_jobs_once
    await orchestrate_daily_jobs_once(session, orchestrator=_FakeOrchestrator())
    assert u_due.id in triggered
    assert u_other.id not in triggered
