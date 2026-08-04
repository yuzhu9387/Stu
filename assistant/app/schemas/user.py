from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class UserCreate(BaseModel):
    name: str
    lark_user_id: Optional[str] = None
    preferences: Optional[dict] = None


class UserRead(BaseModel):
    id: int
    name: str
    lark_user_id: Optional[str]
    preferences: Optional[dict]
    created_at: datetime
    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    name: Optional[str] = None
    preferences: Optional[dict] = None
