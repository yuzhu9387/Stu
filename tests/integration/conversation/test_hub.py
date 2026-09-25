from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import recipe_agent.worker as worker
from recipe_agent.domain.conversation.contracts import ConversationCommand, RunStatus
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.repository import (
    AgentRunRepository,
    ConversationNotFoundError,
    SuggestedActionRepository,
)
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.models import (
    AgentRun,
    Conversation,
    ConversationMessage,
)
from recipe_agent.domain.identity.service import IdentityService
from recipe_agent.infrastructure.db.outbox import OutboxEvent, OutboxRepository
from recipe_agent.infrastructure.jobs.agent_runs import run_agent_job
from recipe_agent.infrastructure.jobs.outbox import publish_pending


async def _scope(identity: IdentityService, email: str):
    delivery = await identity.request_magic_link(email)
    authenticated = await identity.consume_magic_link(delivery.token)
    return authenticated.account.id, authenticated.household.id


async def test_submit_is_transactional_and_deduplicates(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "cook@example.com")
    repository = AgentRunRepository(session_factory)
    hub = ConversationHub(repository)
    command = ConversationCommand(
        account_id=account_id,
        household_id=household_id,
        conversation_id=None,
        allow_conversation_creation=True,
        locale=Locale.EN_US,
        message="What can I cook tonight?",
        transport="web",
        idempotency_key="web-request-1",
    )

    first = await hub.submit_message(command)
    second = await hub.submit_message(command)

    assert first.id == second.id
    assert first.status is RunStatus.QUEUED
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 1
        assert await session.scalar(select(func.count()).select_from(AgentRun)) == 1
        events = tuple(await session.scalars(select(OutboxEvent)))
    assert len(events) == 1
    assert events[0].topic == "agent.run.requested"
    assert events[0].payload == {"run_id": str(first.id)}


class _FailingOutbox(OutboxRepository):
    async def add(self, session, topic, payload):
        raise RuntimeError("outbox unavailable")


async def test_submit_rolls_back_message_and_run_when_outbox_write_fails(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "rollback@example.com")
    hub = ConversationHub(AgentRunRepository(session_factory, outbox=_FailingOutbox()))
    command = ConversationCommand(
        account_id=account_id,
        household_id=household_id,
        conversation_id=None,
        allow_conversation_creation=True,
        locale=Locale.EN_US,
        message="Do not partly save this",
        idempotency_key="rollback-1",
    )

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await hub.submit_message(command)

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 0
        assert await session.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_account_cannot_continue_another_accounts_private_conversation(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    alice_account, alice_household = await _scope(identity_service, "alice@example.com")
    bob_account, bob_household = await _scope(identity_service, "bob@example.com")
    hub = ConversationHub(AgentRunRepository(session_factory))
    alice_run = await hub.submit_message(
        ConversationCommand(
            account_id=alice_account,
            household_id=alice_household,
            conversation_id=None,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Alice's private question",
            idempotency_key="alice-1",
        )
    )

    with pytest.raises(ConversationNotFoundError):
        await hub.submit_message(
            ConversationCommand(
                account_id=bob_account,
                household_id=bob_household,
                conversation_id=alice_run.conversation_id,
                locale=Locale.EN_US,
                message="Try to continue Alice's conversation",
                idempotency_key="bob-1",
            )
        )

    bob_run = await hub.submit_message(
        ConversationCommand(
            account_id=bob_account,
            household_id=bob_household,
            conversation_id=None,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Bob's own question",
            idempotency_key="bob-existing",
        )
    )
    with pytest.raises(ConversationNotFoundError):
        await hub.submit_message(
            ConversationCommand(
                account_id=bob_account,
                household_id=bob_household,
                conversation_id=alice_run.conversation_id,
                locale=Locale.EN_US,
                message="A duplicate key must not bypass conversation privacy",
                idempotency_key="bob-existing",
            )
        )
    assert (
        await hub.get_run(
            bob_run.id,
            account_id=bob_account,
            household_id=bob_household,
        )
        == bob_run
    )


async def test_run_claim_transitions_queued_only_once(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "worker@example.com")
    repository = AgentRunRepository(session_factory)
    run = await ConversationHub(repository).submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            conversation_id=None,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Claim this once",
            idempotency_key="claim-1",
        )
    )

    first_claim = await repository.claim(run.id)
    second_claim = await repository.claim(run.id)

    assert first_claim is not None
    assert first_claim.status is RunStatus.RUNNING
    assert first_claim.started_at is not None
    assert second_claim is None

    completed = await repository.complete(run.id, {"answer": "Finished"})
    repeated_completion = await repository.complete(run.id, {"answer": "Again"})
    failed_after_completion = await repository.fail(run.id, "late_failure")

    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.response == {"answer": "Finished"}
    assert repeated_completion is None
    assert failed_after_completion is None


async def test_expired_run_lease_is_reclaimed_and_stale_attempt_cannot_complete(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "run-lease@example.com")
    repository = AgentRunRepository(session_factory)
    run = await ConversationHub(repository).submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Recover me",
            idempotency_key="run-lease-1",
        )
    )
    start = datetime(2026, 7, 15, tzinfo=UTC)

    first = await repository.claim(run.id, now=start, lease_duration=timedelta(seconds=5))
    second = await repository.claim(
        run.id, now=start + timedelta(seconds=6), lease_duration=timedelta(seconds=5)
    )

    assert first is not None and first.attempt_count == 1
    assert second is not None and second.attempt_count == 2
    assert not await repository.renew_lease(
        run.id,
        attempt_count=first.attempt_count,
        now=start + timedelta(seconds=7),
        lease_duration=timedelta(seconds=5),
    )
    assert await repository.renew_lease(
        run.id,
        attempt_count=second.attempt_count,
        now=start + timedelta(seconds=7),
        lease_duration=timedelta(seconds=5),
    )
    assert (
        await repository.retry_or_fail(
            run.id,
            "stale_failure",
            attempt_count=first.attempt_count,
        )
        == "unchanged"
    )
    assert (
        await repository.complete(run.id, {"answer": "stale"}, attempt_count=first.attempt_count)
        is None
    )
    completed = await repository.complete(
        run.id, {"answer": "fresh"}, attempt_count=second.attempt_count
    )
    assert completed is not None
    assert completed.response == {"answer": "fresh"}


async def test_expired_run_recovery_requeues_before_attempt_limit(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "run-recover@example.com")
    repository = AgentRunRepository(session_factory)
    run = await ConversationHub(repository).submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Recover the worker",
            idempotency_key="run-recover-1",
        )
    )
    start = datetime(2026, 7, 15, tzinfo=UTC)
    assert (
        await repository.claim(run.id, now=start, lease_duration=timedelta(seconds=5)) is not None
    )

    assert await repository.recover_expired(now=start + timedelta(seconds=6)) == 1
    reclaimed = await repository.claim(
        run.id, now=start + timedelta(seconds=7), lease_duration=timedelta(seconds=5)
    )
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2


async def test_stale_published_queued_run_reopens_same_outbox_event_after_quiet_period(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "run-dispatch@example.com")
    repository = AgentRunRepository(session_factory)
    run = await ConversationHub(repository).submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Recover my dispatch",
            idempotency_key="run-dispatch-1",
        )
    )
    published_at = datetime(2026, 7, 16, tzinfo=UTC)
    async with session_factory() as session, session.begin():
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.topic == "agent.run.requested")
        )
        assert event is not None and event.payload == {"run_id": str(run.id)}
        event.attempts = 1
        event.published_at = published_at
        event_id = event.id

    assert (
        await repository.reconcile_stale_queued(
            now=published_at + timedelta(seconds=59),
            stale_after=timedelta(minutes=1),
            max_dispatch_attempts=3,
        )
        == 0
    )
    assert (
        await repository.reconcile_stale_queued(
            now=published_at + timedelta(seconds=61),
            stale_after=timedelta(minutes=1),
            max_dispatch_attempts=3,
        )
        == 1
    )
    async with session_factory() as session:
        refreshed_event = await session.get(OutboxEvent, event_id)
        refreshed_run = await session.get(AgentRun, run.id)
    assert refreshed_event is not None
    assert refreshed_event.published_at is None
    assert refreshed_event.attempts == 1
    assert refreshed_event.last_error == "unclaimed_timeout"
    assert refreshed_run is not None and refreshed_run.status == RunStatus.QUEUED.value


class _RecordingDispatchPublisher:
    def __init__(self) -> None:
        self.events: Counter[UUID] = Counter()

    async def publish(
        self,
        *,
        event_id: UUID,
        topic: str,
        payload: Mapping[str, Any],
    ) -> None:
        assert topic == "agent.run.requested"
        assert set(payload) == {"run_id"}
        self.events[event_id] += 1


class _UnavailableClaimRepository:
    async def claim(self, run_id: UUID):
        del run_id
        raise ConnectionError("database unavailable before claim")


class _CompletingExecutor:
    async def execute(self, run_id: UUID) -> Mapping[str, Any]:
        del run_id
        return {"answer": "recovered"}


async def test_published_run_survives_preclaim_retry_exhaustion_and_completes_after_reconcile(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "run-process@example.com")
    repository = AgentRunRepository(session_factory)
    run = await ConversationHub(repository).submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Recover after the database returns",
            idempotency_key="run-process-reconcile-1",
        )
    )
    outbox = OutboxRepository()
    publisher = _RecordingDispatchPublisher()
    assert await publish_pending(outbox, publisher, session_factory) == 1
    event_id = next(iter(publisher.events))

    for _ in range(3):
        with pytest.raises(ConnectionError, match="database unavailable"):
            await run_agent_job(_UnavailableClaimRepository(), _CompletingExecutor(), run.id)

    async with session_factory() as session:
        still_queued = await session.get(AgentRun, run.id)
        event = await session.get(OutboxEvent, event_id)
    assert still_queued is not None and still_queued.status == RunStatus.QUEUED.value
    assert event is not None and event.published_at is not None

    assert (
        await worker.reconcile_stale_queues(
            run_repository=repository,
            action_repository=SuggestedActionRepository(session_factory),
            now=event.published_at + timedelta(minutes=3),
        )
        == 1
    )
    assert await publish_pending(outbox, publisher, session_factory) == 1
    assert publisher.events == Counter({event_id: 2})

    assert await run_agent_job(repository, _CompletingExecutor(), run.id)
    assert not await run_agent_job(repository, _CompletingExecutor(), run.id)
    completed = await repository.get_for_account(
        run.id,
        account_id=account_id,
        household_id=household_id,
    )
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.response == {"answer": "recovered"}


async def test_queued_run_dispatch_exhaustion_fails_and_queues_lark_terminal(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "lark-dispatch@example.com")
    repository = AgentRunRepository(session_factory)
    run = await ConversationHub(repository).submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Fail after bounded dispatches",
            transport="lark",
            reply_target="oc_dispatch_test",
            idempotency_key="lark-dispatch-exhausted-1",
        )
    )
    published_at = datetime(2026, 7, 16, tzinfo=UTC)
    async with session_factory() as session, session.begin():
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.topic == "agent.run.requested")
        )
        assert event is not None
        event.attempts = 3
        event.published_at = published_at

    assert (
        await repository.reconcile_stale_queued(
            now=published_at + timedelta(minutes=2),
            stale_after=timedelta(minutes=1),
            max_dispatch_attempts=3,
        )
        == 0
    )
    async with session_factory() as session:
        failed = await session.get(AgentRun, run.id)
        events = tuple(await session.scalars(select(OutboxEvent)))
    assert failed is not None
    assert failed.status == RunStatus.FAILED.value
    assert failed.error_code == "dispatch_attempts_exhausted"
    assert failed.completed_at is not None
    assert [event.topic for event in events] == [
        "agent.run.requested",
        "lark.run.completed",
    ]


async def test_lark_chat_uuid_creates_once_then_reuses_private_conversation(
    session_factory: async_sessionmaker[AsyncSession],
    identity_service: IdentityService,
) -> None:
    account_id, household_id = await _scope(identity_service, "lark@example.com")
    hub = ConversationHub(AgentRunRepository(session_factory))
    chat_id = uuid4()

    first = await hub.submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            conversation_id=chat_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="First chat message",
            transport="lark",
            idempotency_key="lark-event-1",
        )
    )
    second = await hub.submit_message(
        ConversationCommand(
            account_id=account_id,
            household_id=household_id,
            conversation_id=chat_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Second chat message",
            transport="lark",
            idempotency_key="lark-event-2",
        )
    )

    assert first.conversation_id == chat_id
    assert second.conversation_id == chat_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 2
        assert await session.scalar(select(func.count()).select_from(AgentRun)) == 2
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 2
