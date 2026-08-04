from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session
from app.repositories.goal import GoalRepository
from app.schemas.goal import GoalRead
from typing import List

router = APIRouter(tags=["goals"])


def get_repo(session: AsyncSession = Depends(get_session)) -> GoalRepository:
    return GoalRepository(session)


@router.get("/api/users/{user_id}/goals", response_model=List[GoalRead])
async def list_goals(user_id: int, repo: GoalRepository = Depends(get_repo)):
    return await repo.list_by_user(user_id)
