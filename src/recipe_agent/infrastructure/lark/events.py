"""Database-backed Lark event idempotency."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class LarkEventReceipt(Base):
    __tablename__ = "lark_event_receipts"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class SqlLarkEventStore:
    """Atomically claim callback IDs through a database uniqueness constraint."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(self, event_id: str) -> bool:
        async with self._session_factory() as session:
            session.add(LarkEventReceipt(event_id=event_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True
