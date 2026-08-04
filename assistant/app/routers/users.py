from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session
from app.models.user import User
from app.repositories.base import BaseRepository
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def get_repo(session: AsyncSession = Depends(get_session)) -> BaseRepository:
    return BaseRepository(User, session)


@router.post("", status_code=201, response_model=UserRead)
async def create_user(data: UserCreate, repo: BaseRepository = Depends(get_repo)):
    return await repo.create(**data.model_dump(exclude_none=True))


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, repo: BaseRepository = Depends(get_repo)):
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(user_id: int, data: UserUpdate, repo: BaseRepository = Depends(get_repo)):
    user = await repo.update(user_id, **data.model_dump(exclude_none=True))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
