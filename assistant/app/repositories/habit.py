from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.habit import Habit
from app.repositories.base import BaseRepository


class HabitRepository(BaseRepository[Habit]):
    def __init__(self, session: AsyncSession):
        super().__init__(Habit, session)

    async def list_by_user(self, user_id: int) -> List[Habit]:
        result = await self.session.execute(select(Habit).where(Habit.user_id == user_id, Habit.active.is_(True)))
        return list(result.scalars().all())
