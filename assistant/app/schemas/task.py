from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    quadrant: Optional[str] = None
    estimated_duration_minutes: Optional[int] = None
    deadline: Optional[datetime] = None
    source: str = "manual"
    goal_id: Optional[int] = None
    parent_task_id: Optional[int] = None


class TaskRead(BaseModel):
    id: int
    user_id: int
    title: str
    description: Optional[str]
    quadrant: Optional[str]
    status: str
    priority_score: Optional[float]
    estimated_duration: Optional[timedelta]
    actual_duration: Optional[timedelta]
    deadline: Optional[datetime]
    source: Optional[str]
    goal_id: Optional[int]
    parent_task_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    quadrant: Optional[str] = None
    status: Optional[str] = None
    estimated_duration_minutes: Optional[int] = None
    deadline: Optional[datetime] = None
    goal_id: Optional[int] = None
