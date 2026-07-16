"""Immutable share snapshot persistence model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class ShareSnapshotRecord(Base):
    __tablename__ = "share_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
