"""Long-running transactional-outbox and agent-run worker entry point."""

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import Celery

from recipe_agent.config import Settings, get_settings
from recipe_agent.domain.conversation.repository import (
    ACTION_EXECUTION_REQUESTED_TOPIC,
    AGENT_RUN_REQUESTED_TOPIC,
    DEFAULT_ACTION_MAX_ATTEMPTS,
    DEFAULT_RUN_MAX_ATTEMPTS,
    AgentRunRepository,
    SuggestedActionRepository,
)
from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.jobs.actions import (
    ACTION_TASK_NAME,
    CeleryActionPublisher,
    run_action_job,
)
from recipe_agent.infrastructure.jobs.agent_runs import (
    AGENT_RUN_TASK_NAME,
    LARK_DELIVERY_TASK_NAME,
    CeleryLarkDeliveryPublisher,
    CeleryRunPublisher,
    LarkDeliveryExecutor,
    run_agent_job,
    run_lark_delivery_job,
)
from recipe_agent.infrastructure.jobs.outbox import publish_pending
from recipe_agent.infrastructure.lark.events import SqlLarkDeliveryStore
from recipe_agent.infrastructure.observability.logging import render_log

celery_app = Celery("recipe_agent")
LarkDeliveryFactory = Callable[[], AbstractAsyncContextManager[LarkDeliveryExecutor]]
_lark_delivery_factory: LarkDeliveryFactory | None = None
_worker_settings: Settings | None = None
QUEUE_DISPATCH_STALE_AFTER = timedelta(minutes=2)
QUEUE_DISPATCH_MAX_ATTEMPTS = max(DEFAULT_ACTION_MAX_ATTEMPTS, DEFAULT_RUN_MAX_ATTEMPTS)


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


def configure_lark_delivery(factory: LarkDeliveryFactory) -> None:
    """Install the Task 7 delivery factory inside the worker process."""

    global _lark_delivery_factory
    _lark_delivery_factory = factory


def create_worker(settings: Settings | None = None) -> Celery:
    """Configure Celery and loop-local runtime factories from one settings object."""

    from recipe_agent.bootstrap import lark_delivery_context

    global _worker_settings
    resolved = settings or get_settings()
    _worker_settings = resolved
    celery_app.conf.broker_url = resolved.redis_url
    celery_app.conf.result_backend = resolved.redis_url
    celery_app.conf.recipe_agent_environment = resolved.environment
    configure_lark_delivery(lambda: lark_delivery_context(resolved))
    return celery_app


def _settings() -> Settings:
    return _worker_settings or get_settings()


@celery_app.task(  # type: ignore[untyped-decorator]
    name=AGENT_RUN_TASK_NAME,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": DEFAULT_RUN_MAX_ATTEMPTS - 1},
    max_retries=DEFAULT_RUN_MAX_ATTEMPTS - 1,
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_agent_run(run_id: str) -> bool:
    """Celery boundary carrying only the durable run UUID."""

    return asyncio.run(_execute_agent_run(UUID(run_id)))


async def _execute_agent_run(run_id: UUID) -> bool:
    settings = _settings()
    from recipe_agent.bootstrap import build_runtime

    runtime = build_runtime(settings)
    try:
        return await run_agent_job(
            runtime.agent_run_repository,
            runtime.agent_run_service,
            run_id,
        )
    finally:
        await runtime.aclose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name=ACTION_TASK_NAME,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": DEFAULT_ACTION_MAX_ATTEMPTS - 1},
    max_retries=DEFAULT_ACTION_MAX_ATTEMPTS - 1,
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_suggested_action(action_id: str) -> bool:
    """Celery boundary carrying only the durable action UUID."""

    return asyncio.run(_execute_suggested_action(UUID(action_id)))


async def _execute_suggested_action(action_id: UUID) -> bool:
    settings = _settings()
    from recipe_agent.bootstrap import build_runtime

    runtime = build_runtime(settings)
    try:
        return await run_action_job(runtime.suggested_action_service, action_id)
    finally:
        await runtime.aclose()


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
    async with _lark_delivery_factory() as delivery:
        return await run_lark_delivery_job(delivery, event_id)


async def run() -> None:
    """Poll committed outbox rows and enqueue durable agent-run tasks."""

    settings = _settings()
    session_factory = create_session_factory(settings)
    repository = OutboxRepository()
    action_repository = SuggestedActionRepository(session_factory)
    run_repository = AgentRunRepository(session_factory)
    delivery_store = SqlLarkDeliveryStore(session_factory)
    publisher = RoutingPublisher(
        CeleryRunPublisher(celery_app),
        CeleryActionPublisher(celery_app),
        CeleryLarkDeliveryPublisher(celery_app),
    )
    try:
        while True:
            now = datetime.now(UTC)
            await reconcile_stale_queues(
                run_repository=run_repository,
                action_repository=action_repository,
                now=now,
            )
            await action_repository.recover_expired(
                now=now,
                max_attempts=DEFAULT_ACTION_MAX_ATTEMPTS,
            )
            await run_repository.recover_expired(
                now=now,
                max_attempts=DEFAULT_RUN_MAX_ATTEMPTS,
            )
            for delivery_event_id in await delivery_store.recover_expired(now=now):
                celery_app.send_task(LARK_DELIVERY_TASK_NAME, args=[str(delivery_event_id)])
            published = await publish_pending(repository, publisher, session_factory)
            await asyncio.sleep(1 if published else 3)
    finally:
        await _dispose_session_factory(session_factory)


async def reconcile_stale_queues(
    *,
    run_repository: AgentRunRepository,
    action_repository: SuggestedActionRepository,
    now: datetime,
) -> int:
    """Reopen old published queue intents using one bounded dispatcher policy."""

    runs = await run_repository.reconcile_stale_queued(
        now=now,
        stale_after=QUEUE_DISPATCH_STALE_AFTER,
        max_dispatch_attempts=QUEUE_DISPATCH_MAX_ATTEMPTS,
    )
    actions = await action_repository.reconcile_stale_queued(
        now=now,
        stale_after=QUEUE_DISPATCH_STALE_AFTER,
        max_dispatch_attempts=QUEUE_DISPATCH_MAX_ATTEMPTS,
    )
    return runs + actions


async def _dispose_session_factory(session_factory: object) -> None:
    factory_options = getattr(session_factory, "kw", None)
    if not isinstance(factory_options, dict):
        return
    dispose = getattr(factory_options.get("bind"), "dispose", None)
    if callable(dispose):
        await dispose()


create_worker()


if __name__ == "__main__":
    asyncio.run(run())
