from datetime import date

from app.models.goal import Goal
from app.models.user import User


async def test_list_goals(client, session):
    user = User(name="Test", lark_user_id="lark_rg2")
    session.add(user)
    await session.commit()
    session.add(Goal(
        user_id=user.id,
        title="Goal A",
        target_value=10,
        unit="x",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
    ))
    await session.commit()
    resp = await client.get(f"/api/users/{user.id}/goals")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
