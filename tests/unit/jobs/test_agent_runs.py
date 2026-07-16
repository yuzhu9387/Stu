import inspect
from uuid import uuid4

import pytest

from recipe_agent.domain.conversation.contracts import AgentRunView, RunStatus
from recipe_agent.infrastructure.jobs.agent_runs import (
    AGENT_RUN_TASK_NAME,
    CeleryRunPublisher,
    run_agent_job,
)
from recipe_agent.worker import celery_app


class RecordingCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def send_task(self, name: str, args: list[str]) -> None:
        self.calls.append((name, args))


async def test_outbox_publisher_enqueues_only_the_run_uuid() -> None:
    celery = RecordingCelery()
    publisher = CeleryRunPublisher(celery)
    run_id = uuid4()

    await publisher.publish(
        event_id=uuid4(),
        topic="agent.run.requested",
        payload={"run_id": str(run_id)},
    )

    assert celery.calls == [(AGENT_RUN_TASK_NAME, [str(run_id)])]


class RecordingRepository:
    def __init__(self, run: AgentRunView) -> None:
        self.run = run
        self.claims = 0
        self.responses: list[dict[str, str]] = []
        self.failures: list[str] = []

    async def claim(self, run_id):
        self.claims += 1
        if self.claims > 1:
            return None
        return self.run

    async def complete(self, run_id, response):
        self.responses.append(dict(response))
        return self.run

    async def fail(self, run_id, error_code):
        self.failures.append(error_code)
        return self.run


class RecordingExecutor:
    def __init__(self) -> None:
        self.run_ids: list[object] = []

    async def execute(self, run_id):
        self.run_ids.append(run_id)
        return {"answer": "done"}


async def test_duplicate_task_delivery_executes_claimed_run_once() -> None:
    run_id = uuid4()
    repository = RecordingRepository(
        AgentRunView(
            id=run_id,
            conversation_id=uuid4(),
            account_id=uuid4(),
            household_id=uuid4(),
            transport="web",
            status=RunStatus.RUNNING,
            created_at="2026-07-15T00:00:00Z",
        )
    )
    executor = RecordingExecutor()

    first = await run_agent_job(repository, executor, run_id)
    second = await run_agent_job(repository, executor, run_id)

    assert first is True
    assert second is False
    assert executor.run_ids == [run_id]
    assert repository.responses == [{"answer": "done"}]


class FailingExecutor:
    async def execute(self, run_id):
        raise TimeoutError("provider details must not be stored")


async def test_executor_failure_marks_run_failed_without_exception_text() -> None:
    run_id = uuid4()
    repository = RecordingRepository(
        AgentRunView(
            id=run_id,
            conversation_id=uuid4(),
            account_id=uuid4(),
            household_id=uuid4(),
            transport="web",
            status=RunStatus.RUNNING,
            created_at="2026-07-15T00:00:00Z",
        )
    )

    with pytest.raises(TimeoutError):
        await run_agent_job(repository, FailingExecutor(), run_id)

    assert repository.failures == ["agent_execution_failed"]


def test_worker_registers_uuid_only_celery_task() -> None:
    task = celery_app.tasks[AGENT_RUN_TASK_NAME]

    assert tuple(inspect.signature(task.run).parameters) == ("run_id",)
