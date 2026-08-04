from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.task import Task
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    def __init__(self, session: AsyncSession):
        super().__init__(Task, session)

    async def list_by_user(self, user_id: int, status: Optional[str] = None, quadrant: Optional[str] = None) -> List[Task]:
        stmt = select(Task).where(Task.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if quadrant is not None:
            stmt = stmt.where(Task.quadrant == quadrant)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
