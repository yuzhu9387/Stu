"""Durable suggested-action publication and worker boundaries."""

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from recipe_agent.domain.conversation.actions import SuggestedActionConflictError
from recipe_agent.domain.conversation.repository import ACTION_EXECUTION_REQUESTED_TOPIC

ACTION_TASK_NAME = "recipe_agent.suggested_actions.execute"


class TaskQueue(Protocol):
    def send_task(self, name: str, args: list[str]) -> object: ...


class ActionExecutor(Protocol):
    async def execute_queued(self, action_id: UUID) -> object: ...


class CeleryActionPublisher:
    """Convert committed action events to UUID-only Celery tasks."""

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
        if topic != ACTION_EXECUTION_REQUESTED_TOPIC:
            raise ValueError(f"Unsupported outbox topic: {topic}")
        action_id = UUID(str(payload["action_id"]))
        self._queue.send_task(ACTION_TASK_NAME, args=[str(action_id)])


async def run_action_job(executor: ActionExecutor, action_id: UUID) -> bool:
    try:
        await executor.execute_queued(action_id)
    except SuggestedActionConflictError:
        return False
    return True
