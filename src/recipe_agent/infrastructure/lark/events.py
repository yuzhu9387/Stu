"""Database-backed Lark event idempotency."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxRepository


class LarkEventReceipt(Base):
    __tablename__ = "lark_event_receipts"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class SqlLarkEventStore:
    """Atomically claim callback IDs through a database uniqueness constraint."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        outbox: OutboxRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox or OutboxRepository()

    async def claim(self, event_id: str) -> bool:
        async with self._session_factory() as session:
            session.add(LarkEventReceipt(event_id=event_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True

    async def is_claimed(self, event_id: str) -> bool:
        async with self._session_factory() as session:
            return await session.get(LarkEventReceipt, event_id) is not None

    async def claim_with_outbox(
        self,
        event_id: str,
        *,
        topic: str,
        payload: dict[str, str],
    ) -> bool:
        """Commit a callback receipt and delivery intent atomically."""

        async with self._session_factory() as session, session.begin():
            try:
                async with session.begin_nested():
                    session.add(LarkEventReceipt(event_id=event_id))
                    await session.flush()
            except IntegrityError:
                return False
            await self._outbox.add(session, topic, payload)
            return True
