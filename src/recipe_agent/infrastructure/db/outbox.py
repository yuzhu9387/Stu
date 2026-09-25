"""Transactional outbox persistence."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class OutboxEvent(Base):
    """One domain event waiting for idempotent external publication."""

    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    @property
    def payload(self) -> Mapping[str, Any]:
        decoded = json.loads(self.payload_json)
        if not isinstance(decoded, dict):
            raise TypeError("Outbox payload must be an object")
        return decoded


class OutboxRepository:
    """Store events in the caller's transaction and track publication state."""

    async def add(
        self,
        session: AsyncSession,
        topic: str,
        payload: Mapping[str, Any],
    ) -> OutboxEvent:
        event = OutboxEvent(
            topic=topic,
            payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        session.add(event)
        await session.flush()
        return event

    async def pending(self, session: AsyncSession, *, limit: int = 100) -> Sequence[OutboxEvent]:
        result = await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
        )
        return tuple(result)

    async def mark_published(self, event: OutboxEvent) -> None:
        event.attempts += 1
        event.published_at = datetime.now(UTC)
        event.last_error = None

    async def mark_failed(self, event: OutboxEvent, error: Exception) -> None:
        event.attempts += 1
        event.last_error = type(error).__name__
