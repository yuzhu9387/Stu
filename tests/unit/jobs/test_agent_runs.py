import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

import recipe_agent.worker as worker
from recipe_agent.domain.conversation.contracts import AgentRunView, RunStatus
from recipe_agent.infrastructure.jobs.agent_runs import (
    AGENT_RUN_TASK_NAME,
    LARK_DELIVERY_TASK_NAME,
    CeleryLarkDeliveryPublisher,
    CeleryRunPublisher,
    run_agent_job,
    run_lark_delivery_job,
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


async def test_lark_outbox_publisher_enqueues_only_kind_and_durable_identifier() -> None:
    celery = RecordingCelery()
    publisher = CeleryLarkDeliveryPublisher(celery)
    run_id = uuid4()
    run_event_id = uuid4()
    linking_event_id = uuid4()

    await publisher.publish(
        event_id=run_event_id,
        topic="lark.run.completed",
        payload={"run_id": str(run_id)},
    )
    await publisher.publish(
        event_id=linking_event_id,
        topic="lark.linking_instructions.requested",
        payload={
            "chat_id": "oc_family_chat",
            "locale": "en-US",
            "source_event_id": "evt_1",
        },
    )

    assert celery.calls == [
        (LARK_DELIVERY_TASK_NAME, [str(run_event_id)]),
        (LARK_DELIVERY_TASK_NAME, [str(linking_event_id)]),
    ]


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

    async def complete(self, run_id, response, *, attempt_count=None):
        self.responses.append(dict(response))
        return self.run

    async def retry_or_fail(self, run_id, error_code, *, attempt_count, max_attempts):
        del run_id, attempt_count, max_attempts
        self.failures.append(error_code)
        return "queued"


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


class RecordingLarkDelivery:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def deliver_outbox(self, event_id):
        self.events.append(event_id)


async def test_lark_delivery_job_routes_without_secret_or_message_payloads() -> None:
    delivery = RecordingLarkDelivery()
    event_id = uuid4()

    assert await run_lark_delivery_job(delivery, event_id) is True

    assert delivery.events == [event_id]


async def test_worker_builds_and_closes_lark_delivery_inside_current_event_loop(
    monkeypatch,
) -> None:
    delivery = RecordingLarkDelivery()
    closed = False

    @asynccontextmanager
    async def factory():
        nonlocal closed
        try:
            yield delivery
        finally:
            closed = True

    monkeypatch.setattr(worker, "_lark_delivery_factory", factory)
    event_id = uuid4()

    assert await worker._deliver_lark_outbox(event_id) is True
    assert delivery.events == [event_id]
    assert closed is True


def test_worker_registers_uuid_only_celery_task() -> None:
    task = celery_app.tasks[AGENT_RUN_TASK_NAME]

    assert tuple(inspect.signature(task.run).parameters) == ("run_id",)
    assert task.max_retries == 2
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


def test_worker_registers_outbox_uuid_only_lark_delivery_task() -> None:
    task = celery_app.tasks[LARK_DELIVERY_TASK_NAME]

    assert tuple(inspect.signature(task.run).parameters) == ("event_id",)
    assert task.max_retries == 5
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


async def test_worker_disposes_its_long_lived_database_engine() -> None:
    class Engine:
        def __init__(self) -> None:
            self.closed = False

        async def dispose(self) -> None:
            self.closed = True

    engine = Engine()

    await worker._dispose_session_factory(type("Factory", (), {"kw": {"bind": engine}})())

    assert engine.closed is True


async def test_dispatcher_reconciles_stale_queued_runs_and_actions_with_bounded_policy() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)

    class Reconciler:
        def __init__(self, result: int) -> None:
            self.result = result
            self.calls: list[dict[str, object]] = []

        async def reconcile_stale_queued(self, **options) -> int:
            self.calls.append(options)
            return self.result

    runs = Reconciler(1)
    actions = Reconciler(2)

    assert (
        await worker.reconcile_stale_queues(
            run_repository=runs,
            action_repository=actions,
            now=now,
        )
        == 3
    )
    expected = {
        "now": now,
        "stale_after": timedelta(minutes=2),
        "max_dispatch_attempts": 3,
    }
    assert runs.calls == [expected]
    assert actions.calls == [expected]


async def test_slow_agent_execution_renews_attempt_fenced_lease() -> None:
    run_id = uuid4()
    run = AgentRunView(
        id=run_id,
        conversation_id=uuid4(),
        account_id=uuid4(),
        household_id=uuid4(),
        transport="web",
        status=RunStatus.RUNNING,
        created_at="2026-07-15T00:00:00Z",
        attempt_count=3,
    )

    class SlowRepository(RecordingRepository):
        def __init__(self) -> None:
            super().__init__(run)
            self.renewals: list[int] = []

        async def renew_lease(self, run_id, *, attempt_count):
            del run_id
            self.renewals.append(attempt_count)
            return True

    class SlowExecutor:
        async def execute(self, run_id):
            del run_id
            await asyncio.sleep(0.04)
            return {"answer": "done"}

    repository = SlowRepository()
    assert await run_agent_job(
        repository,
        SlowExecutor(),
        run_id,
        heartbeat_interval_seconds=0.01,
    )
    assert len(repository.renewals) >= 2
    assert set(repository.renewals) == {3}
