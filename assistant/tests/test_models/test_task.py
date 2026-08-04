from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.models.task import Task
from app.models.user import User


async def test_create_task(session):
    user = User(name="Test", lark_user_id="lark_t1")
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="Write Q2 report", description="Quarterly report", quadrant="urgent_important", status="pending", estimated_duration=timedelta(hours=3), deadline=datetime(2026, 5, 15, tzinfo=timezone.utc), source="manual")
    session.add(task)
    await session.commit()
    result = await session.execute(select(Task).where(Task.user_id == user.id))
    saved = result.scalar_one()
    assert saved.title == "Write Q2 report"
    assert saved.quadrant == "urgent_important"


async def test_task_parent_relationship(session):
    user = User(name="Test", lark_user_id="lark_t2")
    session.add(user)
    await session.commit()
    parent = Task(user_id=user.id, title="Big project", status="pending")
    session.add(parent)
    await session.commit()
    child = Task(user_id=user.id, title="Subtask 1", status="pending", parent_task_id=parent.id)
    session.add(child)
    await session.commit()
    result = await session.execute(select(Task).where(Task.parent_task_id == parent.id))
    saved = result.scalar_one()
    assert saved.title == "Subtask 1"
