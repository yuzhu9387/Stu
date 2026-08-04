from app.models.habit import Habit
from app.models.user import User


async def test_list_habits(client, session):
    user = User(name="Test", lark_user_id="lark_rh2")
    session.add(user)
    await session.commit()
    session.add(Habit(
        user_id=user.id,
        title="Read",
        frequency_type="daily",
        frequency_count=1,
    ))
    await session.commit()
    resp = await client.get(f"/api/users/{user.id}/habits")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
