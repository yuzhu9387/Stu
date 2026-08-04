from app.models.task import Task
from app.models.user import User


async def test_list_tasks(client, session):
    user = User(name="Test", lark_user_id="lark_rt2")
    session.add(user)
    await session.commit()
    session.add_all([
        Task(user_id=user.id, title="Task A", status="pending"),
        Task(user_id=user.id, title="Task B", status="pending"),
    ])
    await session.commit()
    resp = await client.get(f"/api/users/{user.id}/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_list_tasks_filter_by_status(client, session):
    user = User(name="Test", lark_user_id="lark_rt3")
    session.add(user)
    await session.commit()
    session.add(Task(user_id=user.id, title="Task A", status="pending"))
    await session.commit()
    resp = await client.get(f"/api/users/{user.id}/tasks?status=pending")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
