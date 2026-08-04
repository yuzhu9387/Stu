from app.models.task import Task
from app.models.user import User
from app.repositories.task import TaskRepository


async def test_list_by_user(session):
    user = User(name="Test", lark_user_id="lark_tr1")
    other = User(name="Other", lark_user_id="lark_tr2")
    session.add_all([user, other])
    await session.commit()
    repo = TaskRepository(session)
    await repo.create(user_id=user.id, title="Task A", status="pending")
    await repo.create(user_id=user.id, title="Task B", status="completed")
    await repo.create(user_id=other.id, title="Task C", status="pending")
    tasks = await repo.list_by_user(user.id)
    assert len(tasks) == 2


async def test_list_by_user_and_status(session):
    user = User(name="Test", lark_user_id="lark_tr3")
    session.add(user)
    await session.commit()
    repo = TaskRepository(session)
    await repo.create(user_id=user.id, title="Task A", status="pending")
    await repo.create(user_id=user.id, title="Task B", status="completed")
    await repo.create(user_id=user.id, title="Task C", status="pending")
    tasks = await repo.list_by_user(user.id, status="pending")
    assert len(tasks) == 2


async def test_list_by_user_and_quadrant(session):
    user = User(name="Test", lark_user_id="lark_tr4")
    session.add(user)
    await session.commit()
    repo = TaskRepository(session)
    await repo.create(user_id=user.id, title="Urgent", status="pending", quadrant="urgent_important")
    await repo.create(user_id=user.id, title="Not urgent", status="pending", quadrant="important")
    tasks = await repo.list_by_user(user.id, quadrant="urgent_important")
    assert len(tasks) == 1
    assert tasks[0].title == "Urgent"
