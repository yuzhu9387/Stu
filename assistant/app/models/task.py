from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Interval, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    quadrant: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    priority_score: Mapped[Optional[float]] = mapped_column(Float)
    estimated_duration: Mapped[Optional[timedelta]] = mapped_column(Interval)
    actual_duration: Mapped[Optional[timedelta]] = mapped_column(Interval)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source: Mapped[Optional[str]] = mapped_column(String(20), default="manual")
    goal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("goals.id"))
    habit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("habits.id"))
    parent_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
