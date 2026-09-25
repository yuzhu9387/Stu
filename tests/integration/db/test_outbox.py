from collections import Counter
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.jobs.outbox import publish_pending


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: Counter[UUID] = Counter()

    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, Any],
    ) -> None:
        assert topic == "recipe.saved"
        assert payload == {"recipe_id": "r1"}
        self.published[event_id] += 1


async def test_outbox_publishes_committed_event_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = OutboxRepository()
    publisher = RecordingPublisher()
    async with session_factory() as session:
        event = await repository.add(session, "recipe.saved", {"recipe_id": "r1"})
        await session.commit()

    await publish_pending(repository, publisher, session_factory)
    await publish_pending(repository, publisher, session_factory)

    assert publisher.published[event.id] == 1
