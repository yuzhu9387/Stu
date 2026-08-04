from typing import Optional, List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session
from app.repositories.task import TaskRepository
from app.schemas.task import TaskRead

router = APIRouter(tags=["tasks"])


def get_repo(session: AsyncSession = Depends(get_session)) -> TaskRepository:
    return TaskRepository(session)


@router.get("/api/users/{user_id}/tasks", response_model=List[TaskRead])
async def list_tasks(user_id: int, status: Optional[str] = None, quadrant: Optional[str] = None, repo: TaskRepository = Depends(get_repo)):
    return await repo.list_by_user(user_id, status=status, quadrant=quadrant)
