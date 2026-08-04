from datetime import date, datetime, timezone
from sqlalchemy import select
from app.models.reminder import Reminder
from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.report import Report
from app.models.task import Task
from app.models.user import User


async def test_create_reminder(session):
    user = User(name="Test", lark_user_id="lark_r2")
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="Submit report", status="pending")
    session.add(task)
    await session.commit()
    reminder = Reminder(user_id=user.id, trigger_time=datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc), message="Time to submit", type="scheduled", linked_task_id=task.id, status="pending")
    session.add(reminder)
    await session.commit()
    result = await session.execute(select(Reminder).where(Reminder.user_id == user.id))
    saved = result.scalar_one()
    assert saved.message == "Time to submit"


async def test_create_conversation(session):
    user = User(name="Test", lark_user_id="lark_r4")
    session.add(user)
    await session.commit()
    conv = Conversation(user_id=user.id, role="user", content="Add a task", intent="add_task")
    session.add(conv)
    await session.commit()
    result = await session.execute(select(Conversation).where(Conversation.user_id == user.id))
    saved = result.scalar_one()
    assert saved.intent == "add_task"


async def test_create_dialogue_session(session):
    user = User(name="Test", lark_user_id="lark_r5")
    session.add(user)
    await session.commit()
    ds = DialogueSession(user_id=user.id, flow_type="onboarding", current_state="routine", context={"wake_up": "07:00"}, status="active")
    session.add(ds)
    await session.commit()
    result = await session.execute(select(DialogueSession).where(DialogueSession.user_id == user.id))
    saved = result.scalar_one()
    assert saved.flow_type == "onboarding"
    assert saved.context["wake_up"] == "07:00"


async def test_create_report(session):
    user = User(name="Test", lark_user_id="lark_r6")
    session.add(user)
    await session.commit()
    report = Report(user_id=user.id, report_type="daily", period_start=date(2026, 5, 12), period_end=date(2026, 5, 12), data={"completion_rate": 0.85}, ai_insights="Good day")
    session.add(report)
    await session.commit()
    result = await session.execute(select(Report).where(Report.user_id == user.id))
    saved = result.scalar_one()
    assert saved.data["completion_rate"] == 0.85
