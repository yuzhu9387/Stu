from datetime import date as date_type, time
from typing import Optional

from sqlalchemy import Date, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TimeSlot(Base):
    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date_type] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    slot_type: Mapped[str] = mapped_column(String(20))
    linked_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"))
    linked_habit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("habits.id"))
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(100))
