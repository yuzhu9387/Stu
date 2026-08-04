from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

class DialogueSession(Base):
    __tablename__ = "dialogue_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    flow_type: Mapped[str] = mapped_column(String(50))
    current_state: Mapped[Optional[str]] = mapped_column(String(50))
    context: Mapped[Optional[dict]] = mapped_column(JSONVariant, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")
    parent_session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dialogue_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
