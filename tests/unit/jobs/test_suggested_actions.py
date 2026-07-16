import inspect
from uuid import UUID, uuid4

import pytest

from recipe_agent.domain.conversation.actions import SuggestedActionConflictError
from recipe_agent.infrastructure.jobs.actions import (
    ACTION_TASK_NAME,
    CeleryActionPublisher,
    run_action_job,
)
from recipe_agent.worker import celery_app


class RecordingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def send_task(self, name: str, args: list[str]) -> object:
        self.calls.append((name, args))
        return object()


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def execute_queued(self, action_id: UUID) -> object:
        self.calls.append(action_id)
        return object()


@pytest.mark.asyncio
async def test_action_outbox_publisher_and_worker_carry_only_action_id() -> None:
    action_id = uuid4()
    queue = RecordingQueue()
    publisher = CeleryActionPublisher(queue)
    executor = RecordingExecutor()

    await publisher.publish(
        event_id=uuid4(),
        topic="agent.action.requested",
        payload={"action_id": str(action_id)},
    )
    executed = await run_action_job(executor, action_id)

    assert queue.calls == [(ACTION_TASK_NAME, [str(action_id)])]
    assert executor.calls == [action_id]
    assert executed is True


def test_worker_registers_uuid_only_suggested_action_task() -> None:
    task = celery_app.tasks[ACTION_TASK_NAME]

    assert tuple(inspect.signature(task.run).parameters) == ("action_id",)


@pytest.mark.asyncio
async def test_duplicate_action_task_delivery_is_an_acknowledged_no_op() -> None:
    class AlreadyClaimedExecutor:
        async def execute_queued(self, action_id: UUID) -> object:
            del action_id
            raise SuggestedActionConflictError("already claimed")

    assert not await run_action_job(AlreadyClaimedExecutor(), uuid4())
