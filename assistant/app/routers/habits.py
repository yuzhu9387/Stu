from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session
from app.repositories.habit import HabitRepository
from app.schemas.habit import HabitRead

router = APIRouter(tags=["habits"])


def get_repo(session: AsyncSession = Depends(get_session)) -> HabitRepository:
    return HabitRepository(session)


@router.get("/api/users/{user_id}/habits", response_model=List[HabitRead])
async def list_habits(user_id: int, repo: HabitRepository = Depends(get_repo)):
    return await repo.list_by_user(user_id)
