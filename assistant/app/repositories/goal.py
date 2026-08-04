from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.goal import Goal
from app.repositories.base import BaseRepository


class GoalRepository(BaseRepository[Goal]):
    def __init__(self, session: AsyncSession):
        super().__init__(Goal, session)

    async def list_by_user(self, user_id: int) -> List[Goal]:
        result = await self.session.execute(select(Goal).where(Goal.user_id == user_id))
        return list(result.scalars().all())
