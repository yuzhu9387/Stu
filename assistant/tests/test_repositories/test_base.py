from app.models.user import User
from app.repositories.base import BaseRepository


async def test_create(session):
    repo = BaseRepository(User, session)
    user = await repo.create(name="Alice", lark_user_id="lark_base1")
    assert user.id is not None
    assert user.name == "Alice"


async def test_get_by_id(session):
    repo = BaseRepository(User, session)
    user = await repo.create(name="Bob", lark_user_id="lark_base2")
    found = await repo.get_by_id(user.id)
    assert found is not None
    assert found.name == "Bob"


async def test_get_by_id_not_found(session):
    repo = BaseRepository(User, session)
    found = await repo.get_by_id(9999)
    assert found is None


async def test_list_all(session):
    repo = BaseRepository(User, session)
    await repo.create(name="User1", lark_user_id="lark_base3")
    await repo.create(name="User2", lark_user_id="lark_base4")
    users = await repo.list_all()
    assert len(users) == 2


async def test_update(session):
    repo = BaseRepository(User, session)
    user = await repo.create(name="Charlie", lark_user_id="lark_base5")
    updated = await repo.update(user.id, name="Charles")
    assert updated.name == "Charles"


async def test_delete(session):
    repo = BaseRepository(User, session)
    user = await repo.create(name="Dave", lark_user_id="lark_base6")
    deleted = await repo.delete(user.id)
    assert deleted is True
    found = await repo.get_by_id(user.id)
    assert found is None
