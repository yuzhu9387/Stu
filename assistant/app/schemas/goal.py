from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class GoalCreate(BaseModel):
    title: str
    target_value: float
    unit: str
    period_start: date
    period_end: date
    current_value: float = 0.0


class GoalRead(BaseModel):
    id: int
    user_id: int
    title: str
    target_value: float
    current_value: float
    unit: str
    period_start: date
    period_end: date
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    current_value: Optional[float] = None
    status: Optional[str] = None
