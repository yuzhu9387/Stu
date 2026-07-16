"""Database-backed Lark event and delivery idempotency."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxEvent, OutboxRepository


class LarkEventReceipt(Base):
    __tablename__ = "lark_event_receipts"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('processing', 'accepted')",
            name="ck_lark_event_processing_status",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing", server_default="processing"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class LarkDeliveryReceipt(Base):
    __tablename__ = "lark_delivery_receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'delivering', 'delivered', 'failed')",
            name="ck_lark_delivery_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    outbox_event_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("outbox_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class LarkEventSubstitutionError(ValueError):
    """An existing event ID was reused for different verified content."""


class LarkEventBusyError(RuntimeError):
    """A live callback worker still owns the event lease."""


DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS = 6


@dataclass(frozen=True)
class LarkEventLease:
    attempt_count: int


type LarkEventReservation = LarkEventLease | Literal["duplicate", "busy"]


class LarkDeliveryInProgressError(RuntimeError):
    """A live worker lease already owns this delivery."""


class LarkDeliveryAttemptsExhaustedError(RuntimeError):
    """A delivery exhausted its bounded retry budget."""


@dataclass(frozen=True)
class ClaimedLarkDelivery:
    event_id: UUID
    topic: str
    payload: Mapping[str, Any]
    attempt_count: int


async def add_lark_delivery_intent(
    session: AsyncSession,
    outbox: OutboxRepository,
    *,
    topic: str,
    payload: Mapping[str, Any],
    dedupe_key: str,
) -> OutboxEvent:
    event = await outbox.add(session, topic, payload)
    session.add(LarkDeliveryReceipt(outbox_event_id=event.id, dedupe_key=dedupe_key))
    await session.flush()
    return event


class SqlLarkDeliveryStore:
    """Fence Lark sends with durable leases and delivered receipts."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        event_id: UUID,
        *,
        now: datetime | None = None,
        lease_duration: timedelta = timedelta(minutes=2),
        max_attempts: int = DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS,
    ) -> ClaimedLarkDelivery | None:
        current_time = now or datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            exhausted_id = await session.scalar(
                update(LarkDeliveryReceipt)
                .where(
                    LarkDeliveryReceipt.outbox_event_id == event_id,
                    LarkDeliveryReceipt.attempt_count >= max_attempts,
                    or_(
                        LarkDeliveryReceipt.status == "pending",
                        (
                            (LarkDeliveryReceipt.status == "delivering")
                            & (LarkDeliveryReceipt.lease_expires_at <= current_time)
                        ),
                    ),
                )
                .values(
                    status="failed",
                    lease_expires_at=None,
                    error_code="attempts_exhausted",
                    updated_at=current_time,
                )
                .returning(LarkDeliveryReceipt.id)
                .execution_options(synchronize_session=False)
            )
        if exhausted_id is not None:
            raise LarkDeliveryAttemptsExhaustedError("Lark delivery attempts exhausted")
        async with self._session_factory() as session, session.begin():
            receipt = await session.scalar(
                select(LarkDeliveryReceipt).where(LarkDeliveryReceipt.outbox_event_id == event_id)
            )
            if receipt is None:
                raise LookupError("Lark delivery receipt not found")
            if receipt.status == "delivered":
                return None
            if receipt.status == "failed":
                raise LarkDeliveryAttemptsExhaustedError("Lark delivery attempts exhausted")
            if (
                receipt.status == "delivering"
                and receipt.lease_expires_at is not None
                and _as_utc(receipt.lease_expires_at) > _as_utc(current_time)
            ):
                raise LarkDeliveryInProgressError("Lark delivery is in progress")
            claimed_id = await session.scalar(
                update(LarkDeliveryReceipt)
                .where(
                    LarkDeliveryReceipt.id == receipt.id,
                    LarkDeliveryReceipt.status.in_(("pending", "delivering")),
                    or_(
                        LarkDeliveryReceipt.status == "pending",
                        LarkDeliveryReceipt.lease_expires_at <= current_time,
                    ),
                )
                .values(
                    status="delivering",
                    attempt_count=LarkDeliveryReceipt.attempt_count + 1,
                    lease_expires_at=current_time + lease_duration,
                    error_code=None,
                    updated_at=current_time,
                )
                .returning(LarkDeliveryReceipt.id)
                .execution_options(synchronize_session=False)
            )
            if claimed_id is None:
                raise LarkDeliveryInProgressError("Lark delivery is in progress")
            await session.flush()
            await session.refresh(receipt)
            event = await session.get(OutboxEvent, event_id)
            if event is None:
                raise LookupError("Lark delivery intent not found")
            return ClaimedLarkDelivery(
                event_id=event.id,
                topic=event.topic,
                payload=dict(event.payload),
                attempt_count=receipt.attempt_count,
            )

    async def mark_delivered(
        self, event_id: UUID, *, attempt_count: int, now: datetime | None = None
    ) -> bool:
        current_time = now or datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            delivered_id = await session.scalar(
                update(LarkDeliveryReceipt)
                .where(
                    LarkDeliveryReceipt.outbox_event_id == event_id,
                    LarkDeliveryReceipt.status == "delivering",
                    LarkDeliveryReceipt.attempt_count == attempt_count,
                )
                .values(
                    status="delivered",
                    lease_expires_at=None,
                    delivered_at=current_time,
                    error_code=None,
                    updated_at=current_time,
                )
                .returning(LarkDeliveryReceipt.id)
                .execution_options(synchronize_session=False)
            )
            return delivered_id is not None

    async def mark_retry(
        self,
        event_id: UUID,
        *,
        attempt_count: int,
        error_code: str,
        max_attempts: int = DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            receipt_id = await session.scalar(
                update(LarkDeliveryReceipt)
                .where(
                    LarkDeliveryReceipt.outbox_event_id == event_id,
                    LarkDeliveryReceipt.status == "delivering",
                    LarkDeliveryReceipt.attempt_count == attempt_count,
                )
                .values(
                    status=("failed" if attempt_count >= max_attempts else "pending"),
                    lease_expires_at=None,
                    error_code=error_code,
                    updated_at=datetime.now(UTC),
                )
                .returning(LarkDeliveryReceipt.id)
                .execution_options(synchronize_session=False)
            )
            return receipt_id is not None

    async def recover_expired(self, *, now: datetime, limit: int = 100) -> tuple[UUID, ...]:
        """Return expired sends to pending so a worker can enqueue them again."""

        async with self._session_factory() as session, session.begin():
            ids = tuple(
                await session.scalars(
                    select(LarkDeliveryReceipt.id)
                    .where(
                        LarkDeliveryReceipt.status == "delivering",
                        LarkDeliveryReceipt.lease_expires_at <= now,
                    )
                    .order_by(LarkDeliveryReceipt.lease_expires_at)
                    .limit(limit)
                )
            )
            recovered: list[UUID] = []
            for receipt_id in ids:
                event_id = await session.scalar(
                    update(LarkDeliveryReceipt)
                    .where(
                        LarkDeliveryReceipt.id == receipt_id,
                        LarkDeliveryReceipt.status == "delivering",
                        LarkDeliveryReceipt.lease_expires_at <= now,
                    )
                    .values(
                        status="pending",
                        lease_expires_at=None,
                        error_code="worker_lease_expired",
                        updated_at=now,
                    )
                    .returning(LarkDeliveryReceipt.outbox_event_id)
                    .execution_options(synchronize_session=False)
                )
                if event_id is not None:
                    recovered.append(event_id)
            return tuple(recovered)


class SqlLarkEventStore:
    """Reserve verified callbacks before any externally visible side effect."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._outbox = OutboxRepository()

    async def reserve(
        self,
        event_id: str,
        fingerprint_hash: str,
        *,
        now: datetime | None = None,
        lease_duration: timedelta = timedelta(minutes=2),
    ) -> LarkEventReservation:
        current_time = now or datetime.now(UTC)
        lease_expires_at = current_time + lease_duration
        async with self._session_factory() as session, session.begin():
            inserted = False
            try:
                async with session.begin_nested():
                    session.add(
                        LarkEventReceipt(
                            event_id=event_id,
                            fingerprint_hash=fingerprint_hash,
                            lease_expires_at=lease_expires_at,
                            updated_at=current_time,
                        )
                    )
                    await session.flush()
                    inserted = True
            except IntegrityError:
                pass
            if inserted:
                return LarkEventLease(attempt_count=1)

            receipt = await session.scalar(
                select(LarkEventReceipt).where(LarkEventReceipt.event_id == event_id)
            )
            if receipt is None:
                return "busy"
            if (
                receipt.processing_status == "accepted"
                and receipt.fingerprint_hash == "0" * 64
                and receipt.outcome == "legacy"
            ):
                return "duplicate"
            if receipt.fingerprint_hash != fingerprint_hash:
                raise LarkEventSubstitutionError("Lark event ID content mismatch")
            if receipt.processing_status == "accepted":
                return "duplicate"
            if receipt.lease_expires_at is not None and _as_utc(receipt.lease_expires_at) > _as_utc(
                current_time
            ):
                return "busy"

            attempt_count = await session.scalar(
                update(LarkEventReceipt)
                .where(
                    LarkEventReceipt.event_id == event_id,
                    LarkEventReceipt.fingerprint_hash == fingerprint_hash,
                    LarkEventReceipt.processing_status == "processing",
                    or_(
                        LarkEventReceipt.lease_expires_at.is_(None),
                        LarkEventReceipt.lease_expires_at <= current_time,
                    ),
                )
                .values(
                    attempt_count=LarkEventReceipt.attempt_count + 1,
                    lease_expires_at=lease_expires_at,
                    updated_at=current_time,
                )
                .returning(LarkEventReceipt.attempt_count)
                .execution_options(synchronize_session=False)
            )
            return (
                LarkEventLease(attempt_count=attempt_count) if attempt_count is not None else "busy"
            )

    async def accept(
        self,
        event_id: str,
        fingerprint_hash: str,
        outcome: str,
        *,
        attempt_count: int,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            receipt = await session.get(LarkEventReceipt, event_id)
            if receipt is None:
                raise LookupError("Lark event reservation not found")
            if receipt.fingerprint_hash != fingerprint_hash:
                raise LarkEventSubstitutionError("Lark event ID content mismatch")
            if receipt.processing_status == "accepted":
                return receipt.attempt_count == attempt_count
            accepted_id = await session.scalar(
                update(LarkEventReceipt)
                .where(
                    LarkEventReceipt.event_id == event_id,
                    LarkEventReceipt.fingerprint_hash == fingerprint_hash,
                    LarkEventReceipt.processing_status == "processing",
                    LarkEventReceipt.attempt_count == attempt_count,
                )
                .values(
                    processing_status="accepted",
                    outcome=outcome,
                    lease_expires_at=None,
                    updated_at=current_time,
                )
                .returning(LarkEventReceipt.event_id)
                .execution_options(synchronize_session=False)
            )
            return accepted_id is not None

    async def accept_with_delivery(
        self,
        event_id: str,
        fingerprint_hash: str,
        outcome: str,
        *,
        attempt_count: int,
        topic: str,
        payload: Mapping[str, Any],
        dedupe_key: str,
        now: datetime | None = None,
    ) -> bool:
        """Fence receipt acceptance and its identity-response intent atomically."""

        current_time = now or datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            accepted_id = await session.scalar(
                update(LarkEventReceipt)
                .where(
                    LarkEventReceipt.event_id == event_id,
                    LarkEventReceipt.fingerprint_hash == fingerprint_hash,
                    LarkEventReceipt.processing_status == "processing",
                    LarkEventReceipt.attempt_count == attempt_count,
                )
                .values(
                    processing_status="accepted",
                    outcome=outcome,
                    lease_expires_at=None,
                    updated_at=current_time,
                )
                .returning(LarkEventReceipt.event_id)
                .execution_options(synchronize_session=False)
            )
            if accepted_id is None:
                return False
            await add_lark_delivery_intent(
                session,
                self._outbox,
                topic=topic,
                payload=payload,
                dedupe_key=dedupe_key,
            )
            return True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS",
    "LarkDeliveryAttemptsExhaustedError",
    "LarkDeliveryInProgressError",
    "LarkDeliveryReceipt",
    "LarkEventBusyError",
    "LarkEventLease",
    "LarkEventReceipt",
    "LarkEventReservation",
    "LarkEventSubstitutionError",
    "SqlLarkDeliveryStore",
    "SqlLarkEventStore",
    "add_lark_delivery_intent",
]
