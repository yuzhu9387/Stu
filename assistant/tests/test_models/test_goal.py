from datetime import date
from sqlalchemy import select
from app.models.goal import Goal
from app.models.user import User


async def test_create_goal(session):
    user = User(name="Test", lark_user_id="lark_g1")
    session.add(user)
    await session.commit()
    goal = Goal(user_id=user.id, title="Read 12 books", target_value=12.0, current_value=5.0, unit="books", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), status="active")
    session.add(goal)
    await session.commit()
    result = await session.execute(select(Goal).where(Goal.user_id == user.id))
    saved = result.scalar_one()
    assert saved.title == "Read 12 books"
    assert saved.target_value == 12.0
    assert saved.current_value == 5.0
