"""Outbox publisher worker."""

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.infrastructure.db.outbox import OutboxRepository


class EventPublisher(Protocol):
    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, Any],
    ) -> None: ...


async def publish_pending(
    repository: OutboxRepository,
    publisher: EventPublisher,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = 100,
) -> int:
    """Publish each committed pending event and persist its receipt."""

    published = 0
    async with session_factory() as session:
        events = await repository.pending(session, limit=limit)
        for event in events:
            try:
                await publisher.publish(
                    event_id=event.id,
                    topic=event.topic,
                    payload=event.payload,
                )
            except Exception as error:
                await repository.mark_failed(event, error)
            else:
                await repository.mark_published(event)
                published += 1
        await session.commit()
    return published
