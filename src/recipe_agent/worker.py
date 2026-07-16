"""Long-running transactional-outbox and agent-run worker entry point."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import Celery

from recipe_agent.config import get_settings
from recipe_agent.domain.conversation.repository import (
    ACTION_EXECUTION_REQUESTED_TOPIC,
    AGENT_RUN_REQUESTED_TOPIC,
    DEFAULT_ACTION_MAX_ATTEMPTS,
    AgentRunRepository,
    SuggestedActionRepository,
)
from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.jobs.actions import (
    ACTION_TASK_NAME,
    ActionExecutor,
    CeleryActionPublisher,
    run_action_job,
)
from recipe_agent.infrastructure.jobs.agent_runs import (
    AGENT_RUN_TASK_NAME,
    LARK_DELIVERY_TASK_NAME,
    AgentRunExecutor,
    CeleryLarkDeliveryPublisher,
    CeleryRunPublisher,
    LarkDeliveryExecutor,
    run_agent_job,
    run_lark_delivery_job,
)
from recipe_agent.infrastructure.jobs.outbox import publish_pending
from recipe_agent.infrastructure.observability.logging import render_log

celery_app = Celery("recipe_agent")
ExecutorFactory = Callable[[AgentRunRepository], AgentRunExecutor]
ActionExecutorFactory = Callable[[SuggestedActionRepository], ActionExecutor]
LarkDeliveryFactory = Callable[[], LarkDeliveryExecutor]
_executor_factory: ExecutorFactory | None = None
_action_executor_factory: ActionExecutorFactory | None = None
_lark_delivery_factory: LarkDeliveryFactory | None = None


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

    def __init__(
        self,
        celery_publisher: CeleryRunPublisher,
        action_publisher: CeleryActionPublisher,
        lark_publisher: CeleryLarkDeliveryPublisher,
    ) -> None:
        self._celery_publisher = celery_publisher
        self._action_publisher = action_publisher
        self._lark_publisher = lark_publisher
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
        if topic == ACTION_EXECUTION_REQUESTED_TOPIC:
            await self._action_publisher.publish(
                event_id=event_id,
                topic=topic,
                payload=payload,
            )
            return
        if topic.startswith("lark."):
            await self._lark_publisher.publish(
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


def configure_suggested_action_executor(factory: ActionExecutorFactory) -> None:
    """Install the durable suggested-action executor inside the worker process."""

    global _action_executor_factory
    _action_executor_factory = factory


def configure_lark_delivery(factory: LarkDeliveryFactory) -> None:
    """Install the Task 7 delivery factory inside the worker process."""

    global _lark_delivery_factory
    _lark_delivery_factory = factory


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


@celery_app.task(name=ACTION_TASK_NAME)  # type: ignore[untyped-decorator]
def execute_suggested_action(action_id: str) -> bool:
    """Celery boundary carrying only the durable action UUID."""

    return asyncio.run(_execute_suggested_action(UUID(action_id)))


async def _execute_suggested_action(action_id: UUID) -> bool:
    settings = get_settings()
    repository = SuggestedActionRepository(create_session_factory(settings))
    if _action_executor_factory is None:
        raise RuntimeError("Suggested action executor is not configured")
    return await run_action_job(_action_executor_factory(repository), action_id)


@celery_app.task(  # type: ignore[untyped-decorator]
    name=LARK_DELIVERY_TASK_NAME,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
)
def deliver_lark_outbox(event_id: str) -> bool:
    """Celery boundary carrying only the durable outbox UUID."""

    return asyncio.run(_deliver_lark_outbox(UUID(event_id)))


async def _deliver_lark_outbox(event_id: UUID) -> bool:
    if _lark_delivery_factory is None:
        raise RuntimeError("Lark delivery is not configured")
    return await run_lark_delivery_job(_lark_delivery_factory(), event_id)


async def run() -> None:
    """Poll committed outbox rows and enqueue durable agent-run tasks."""

    settings = get_settings()
    celery_app.conf.broker_url = settings.redis_url
    celery_app.conf.result_backend = settings.redis_url
    session_factory = create_session_factory(settings)
    repository = OutboxRepository()
    action_repository = SuggestedActionRepository(session_factory)
    publisher = RoutingPublisher(
        CeleryRunPublisher(celery_app),
        CeleryActionPublisher(celery_app),
        CeleryLarkDeliveryPublisher(celery_app),
    )
    while True:
        await action_repository.recover_expired(
            now=datetime.now(UTC),
            max_attempts=DEFAULT_ACTION_MAX_ATTEMPTS,
        )
        published = await publish_pending(repository, publisher, session_factory)
        await asyncio.sleep(1 if published else 3)


if __name__ == "__main__":
    asyncio.run(run())
