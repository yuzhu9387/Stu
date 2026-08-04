from sqlalchemy import select
from app.models.habit import Habit
from app.models.user import User


async def test_create_habit(session):
    user = User(name="Test", lark_user_id="lark_h1")
    session.add(user)
    await session.commit()
    habit = Habit(user_id=user.id, title="Workout", frequency_type="weekly", frequency_count=3, preferred_time_slots=[{"day": "mon", "time": "18:00"}])
    session.add(habit)
    await session.commit()
    result = await session.execute(select(Habit).where(Habit.user_id == user.id))
    saved = result.scalar_one()
    assert saved.title == "Workout"
    assert saved.frequency_count == 3
    assert saved.active is True
