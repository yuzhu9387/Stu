"""Celery publication and idempotent agent-run execution boundaries."""

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.contracts import AgentRunView
from recipe_agent.domain.conversation.repository import (
    AGENT_RUN_REQUESTED_TOPIC,
    LARK_RUN_COMPLETED_TOPIC,
)
from recipe_agent.infrastructure.lark.delivery import (
    LARK_LINKED_TOPIC,
    LARK_LINKING_INSTRUCTIONS_TOPIC,
)

AGENT_RUN_TASK_NAME = "recipe_agent.agent_runs.execute"
LARK_DELIVERY_TASK_NAME = "recipe_agent.lark.deliver"


class TaskQueue(Protocol):
    def send_task(self, name: str, args: list[str]) -> object: ...


class RunLifecycle(Protocol):
    async def claim(self, run_id: UUID) -> AgentRunView | None: ...

    async def complete(
        self, run_id: UUID, response: Mapping[str, JsonValue]
    ) -> AgentRunView | None: ...

    async def fail(self, run_id: UUID, error_code: str) -> AgentRunView | None: ...


class AgentRunExecutor(Protocol):
    async def execute(self, run_id: UUID) -> Mapping[str, JsonValue]: ...


class LarkDeliveryExecutor(Protocol):
    async def deliver_outbox(self, event_id: UUID) -> None: ...


class CeleryRunPublisher:
    """Convert committed run-request events to UUID-only Celery tasks."""

    def __init__(self, queue: TaskQueue) -> None:
        self._queue = queue

    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, object],
    ) -> None:
        del event_id
        if topic != AGENT_RUN_REQUESTED_TOPIC:
            raise ValueError(f"Unsupported outbox topic: {topic}")
        run_id = UUID(str(payload["run_id"]))
        self._queue.send_task(AGENT_RUN_TASK_NAME, args=[str(run_id)])


class CeleryLarkDeliveryPublisher:
    """Queue only the durable outbox UUID, never message text or consent tokens."""

    def __init__(self, queue: TaskQueue) -> None:
        self._queue = queue

    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, object],
    ) -> None:
        del payload
        if topic not in {
            LARK_RUN_COMPLETED_TOPIC,
            LARK_LINKING_INSTRUCTIONS_TOPIC,
            LARK_LINKED_TOPIC,
        }:
            raise ValueError(f"Unsupported Lark outbox topic: {topic}")
        self._queue.send_task(LARK_DELIVERY_TASK_NAME, args=[str(event_id)])


async def run_agent_job(
    repository: RunLifecycle,
    executor: AgentRunExecutor,
    run_id: UUID,
) -> bool:
    """Claim and execute one run; duplicate task delivery is a no-op."""

    claimed = await repository.claim(run_id)
    if claimed is None:
        return False
    try:
        response = await executor.execute(run_id)
    except Exception:
        await repository.fail(run_id, "agent_execution_failed")
        raise
    await repository.complete(run_id, response)
    return True


async def run_lark_delivery_job(
    delivery: LarkDeliveryExecutor,
    event_id: UUID,
) -> bool:
    await delivery.deliver_outbox(event_id)
    return True
