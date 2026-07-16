"""Long-running transactional-outbox and agent-run worker entry point."""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from celery import Celery

from recipe_agent.config import get_settings
from recipe_agent.domain.conversation.repository import (
    AGENT_RUN_REQUESTED_TOPIC,
    AgentRunRepository,
)
from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.jobs.agent_runs import (
    AGENT_RUN_TASK_NAME,
    AgentRunExecutor,
    CeleryRunPublisher,
    run_agent_job,
)
from recipe_agent.infrastructure.jobs.outbox import publish_pending
from recipe_agent.infrastructure.observability.logging import render_log

celery_app = Celery("recipe_agent")
ExecutorFactory = Callable[[AgentRunRepository], AgentRunExecutor]
_executor_factory: ExecutorFactory | None = None


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


class RoutingPublisher:
    """Route run requests to Celery while preserving existing event sinks."""

    def __init__(self, celery_publisher: CeleryRunPublisher) -> None:
        self._celery_publisher = celery_publisher
        self._fallback = StructuredLogPublisher()

    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, Any],
    ) -> None:
        if topic == AGENT_RUN_REQUESTED_TOPIC:
            await self._celery_publisher.publish(
                event_id=event_id,
                topic=topic,
                payload=payload,
            )
            return
        await self._fallback.publish(event_id=event_id, topic=topic, payload=payload)


def configure_agent_run_executor(factory: ExecutorFactory) -> None:
    """Install the Task 4 executor factory inside the worker process."""

    global _executor_factory
    _executor_factory = factory


@celery_app.task(name=AGENT_RUN_TASK_NAME)  # type: ignore[untyped-decorator]
def execute_agent_run(run_id: str) -> bool:
    """Celery boundary carrying only the durable run UUID."""

    return asyncio.run(_execute_agent_run(UUID(run_id)))


async def _execute_agent_run(run_id: UUID) -> bool:
    settings = get_settings()
    repository = AgentRunRepository(create_session_factory(settings))
    if _executor_factory is None:
        raise RuntimeError("Agent run executor is not configured")
    return await run_agent_job(repository, _executor_factory(repository), run_id)


async def run() -> None:
    """Poll committed outbox rows and enqueue durable agent-run tasks."""

    settings = get_settings()
    celery_app.conf.broker_url = settings.redis_url
    celery_app.conf.result_backend = settings.redis_url
    session_factory = create_session_factory(settings)
    repository = OutboxRepository()
    publisher = RoutingPublisher(CeleryRunPublisher(celery_app))
    while True:
        published = await publish_pending(repository, publisher, session_factory)
        await asyncio.sleep(1 if published else 3)


if __name__ == "__main__":
    asyncio.run(run())
