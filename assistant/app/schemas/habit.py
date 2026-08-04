from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class HabitCreate(BaseModel):
    title: str
    frequency_type: str
    frequency_count: int = 1
    preferred_time_slots: Optional[list] = None


class HabitRead(BaseModel):
    id: int
    user_id: int
    title: str
    frequency_type: str
    frequency_count: int
    preferred_time_slots: Optional[list]
    active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class HabitUpdate(BaseModel):
    title: Optional[str] = None
    frequency_type: Optional[str] = None
    frequency_count: Optional[int] = None
    preferred_time_slots: Optional[list] = None
    active: Optional[bool] = None
