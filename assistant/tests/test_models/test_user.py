from sqlalchemy import select
from app.models.user import User


async def test_create_user(session):
    user = User(name="Test User", lark_user_id="lark_123", preferences={"wake_up": "07:00", "sleep": "23:00"})
    session.add(user)
    await session.commit()
    result = await session.execute(select(User).where(User.lark_user_id == "lark_123"))
    saved = result.scalar_one()
    assert saved.name == "Test User"
    assert saved.preferences["wake_up"] == "07:00"


async def test_user_lark_id_unique(session):
    user1 = User(name="User 1", lark_user_id="lark_same")
    user2 = User(name="User 2", lark_user_id="lark_same")
    session.add(user1)
    await session.commit()
    session.add(user2)
    try:
        await session.commit()
        assert False, "Should have raised IntegrityError"
    except Exception:
        await session.rollback()
