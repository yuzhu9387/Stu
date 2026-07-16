from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.conversation.contracts import ConversationCommand, RunStatus
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.repository import (
    AgentRunRepository,
    ConversationNotFoundError,
)
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.models import (
    AgentRun,
    Conversation,
    ConversationMessage,
)
from recipe_agent.domain.identity.service import IdentityService
from recipe_agent.infrastructure.db.outbox import OutboxEvent, OutboxRepository


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
    assert await repository.complete(
        run.id, {"answer": "stale"}, attempt_count=first.attempt_count
    ) is None
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
    assert await repository.claim(
        run.id, now=start, lease_duration=timedelta(seconds=5)
    ) is not None

    assert await repository.recover_expired(now=start + timedelta(seconds=6)) == 1
    reclaimed = await repository.claim(
        run.id, now=start + timedelta(seconds=7), lease_duration=timedelta(seconds=5)
    )
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2


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
