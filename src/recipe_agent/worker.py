"""Long-running outbox worker entry point."""

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from recipe_agent.config import get_settings
from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.jobs.outbox import publish_pending
from recipe_agent.infrastructure.observability.logging import render_log


class StructuredLogPublisher:
    """Operational event sink that never writes private payload values."""

    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, Any],
    ) -> None:
        print(
            render_log(
                {
                    "event": "outbox.published",
                    "event_id": str(event_id),
                    "topic": topic,
                    "payload_fields": sorted(payload),
                }
            ),
            flush=True,
        )


async def run() -> None:
    """Poll committed outbox rows and publish with stable event identifiers."""

    session_factory = create_session_factory(get_settings())
    repository = OutboxRepository()
    publisher = StructuredLogPublisher()
    while True:
        published = await publish_pending(repository, publisher, session_factory)
        await asyncio.sleep(1 if published else 3)


if __name__ == "__main__":
    asyncio.run(run())
