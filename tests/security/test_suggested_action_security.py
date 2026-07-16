import asyncio
import hashlib
import os
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from recipe_agent.domain.conversation.actions import (
    ActionArguments,
    ActionExecutionError,
    InvalidSuggestedActionError,
    SaveRecipeArguments,
    SaveRecipeMutationHandler,
    SuggestedActionConflictError,
    SuggestedActionNotFoundError,
    SuggestedActionRepository,
    SuggestedActionService,
)
from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.domain.conversation.repository import AgentRunRepository
from recipe_agent.domain.conversation.responses import ActionArgument, SuggestedActionDraft
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.models import SuggestedActionRecord
from recipe_agent.domain.identity.service import HouseholdScope, IdentityService
from recipe_agent.domain.planning.contracts import PlanSlot
from recipe_agent.domain.recipes.contracts import (
    RecipeIngredientCandidate,
    RecipeStepCandidate,
)
from recipe_agent.domain.recipes.models import Recipe
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxEvent
from recipe_agent.infrastructure.lark.crypto import ActionContextSigner


class RecordingHandler:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[UUID] = []
        self.failure = failure

    async def execute(
        self, *, actor: HouseholdScope, arguments: ActionArguments, action_id: UUID
    ) -> Mapping[str, object]:
        self.calls.append(action_id)
        if self.failure is not None:
            raise self.failure
        return {"saved": True}


def _draft(arguments: tuple[ActionArgument, ...] | None = None) -> SuggestedActionDraft:
    return SuggestedActionDraft(
        type="save_recipe",
        arguments=arguments
        or (
            ActionArgument(name="name", value_json='"Soup"'),
            ActionArgument(name="ingredients", value_json="[]"),
            ActionArgument(name="steps", value_json="[]"),
        ),
    )


async def _identity_and_run(
    session_factory: async_sessionmaker[AsyncSession], email: str = "owner@example.com"
) -> tuple[HouseholdScope, UUID]:
    identity = IdentityService(session_factory=session_factory)
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link(email)).token
    )
    scope = HouseholdScope(authenticated.account.id, authenticated.household.id)
    run, _ = await AgentRunRepository(session_factory).create_idempotent(
        ConversationCommand(
            account_id=scope.account_id,
            household_id=scope.household_id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Save it",
            idempotency_key=f"run-{uuid4()}",
        )
    )
    return scope, run.id


def _service(
    session_factory: async_sessionmaker[AsyncSession],
    handler: RecordingHandler,
    *,
    now=None,
    lifetime: timedelta = timedelta(minutes=10),
) -> SuggestedActionService:
    return SuggestedActionService(
        repository=SuggestedActionRepository(session_factory),
        signer=ActionContextSigner("security-test-signing-key"),
        handlers={"save_recipe": handler},
        now=now,
        lifetime=lifetime,
    )


@pytest.mark.asyncio
async def test_issue_rejects_duplicate_missing_unknown_and_invalid_json_arguments(
    session_factory,
) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    service = _service(session_factory, RecordingHandler())
    invalid_arguments = (
        (
            ActionArgument(name="name", value_json='"Soup"'),
            ActionArgument(name="name", value_json='"Stew"'),
            ActionArgument(name="ingredients", value_json="[]"),
            ActionArgument(name="steps", value_json="[]"),
        ),
        (ActionArgument(name="name", value_json='"Soup"'),),
        (
            ActionArgument(name="name", value_json='"Soup"'),
            ActionArgument(name="ingredients", value_json="[]"),
            ActionArgument(name="steps", value_json="[]"),
            ActionArgument(name="account_id", value_json=f'"{scope.account_id}"'),
        ),
        (
            ActionArgument(name="name", value_json='"Soup"'),
            ActionArgument(name="ingredients", value_json="not-json"),
            ActionArgument(name="steps", value_json="[]"),
        ),
        (
            ActionArgument(name="name", value_json='"Soup"'),
            ActionArgument(name="ingredients", value_json="[]"),
            ActionArgument(
                name="steps",
                value_json='[{"number":1,"text":"Boil."}]',
            ),
        ),
    )

    for arguments in invalid_arguments:
        with pytest.raises((InvalidSuggestedActionError, ValidationError)):
            await service.issue(_draft(arguments), actor=scope, source_run_id=run_id)

    async with session_factory() as session:
        assert (await session.scalars(select(SuggestedActionRecord))).all() == []


@pytest.mark.asyncio
async def test_raw_token_is_never_persisted_and_claims_bind_every_scope_field(
    session_factory,
) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    service = _service(session_factory, RecordingHandler())

    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)

    async with session_factory() as session:
        record = (await session.scalars(select(SuggestedActionRecord))).one()
    claims = ActionContextSigner("security-test-signing-key").loads(issued.token)
    assert record.token_hash == hashlib.sha256(issued.token.encode()).hexdigest()
    assert issued.token not in record.token_hash
    assert claims == {
        "account_id": str(scope.account_id),
        "action_id": str(issued.id),
        "action_type": "save_recipe",
        "expires_at": issued.expires_at.isoformat().replace("+00:00", "Z"),
        "household_id": str(scope.household_id),
        "source_run_id": str(run_id),
    }


@pytest.mark.asyncio
async def test_tampered_and_expired_tokens_are_unauthorized_without_dispatch(
    session_factory,
) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    now = datetime(2026, 7, 16, tzinfo=UTC)
    handler = RecordingHandler()
    service = _service(
        session_factory,
        handler,
        now=lambda: now,
        lifetime=timedelta(seconds=1),
    )
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)
    position = len(issued.token) // 2
    replacement = "A" if issued.token[position] != "A" else "B"
    tampered_token = issued.token[:position] + replacement + issued.token[position + 1 :]

    with pytest.raises(InvalidSuggestedActionError):
        await service.consume(tampered_token, actor=scope)
    expired_service = _service(session_factory, handler, now=lambda: now + timedelta(seconds=2))
    with pytest.raises(InvalidSuggestedActionError):
        await expired_service.consume(issued.token, actor=scope)
    assert handler.calls == []


@pytest.mark.asyncio
async def test_click_only_queues_a_durable_action_without_dispatch(session_factory) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    handler = RecordingHandler()
    service = _service(session_factory, handler)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)

    result = await service.consume(issued.token, actor=scope)

    assert result.status == "queued"
    assert result.result is None
    assert handler.calls == []
    async with session_factory() as session:
        record = await session.get(SuggestedActionRecord, issued.id)
        events = (await session.scalars(select(OutboxEvent))).all()
    assert record is not None
    assert record.execution_status == "queued"
    assert record.consumed_by_account_id == scope.account_id
    assert [
        (event.topic, event.payload) for event in events if event.topic == "agent.action.requested"
    ] == [("agent.action.requested", {"action_id": str(issued.id)})]


@pytest.mark.asyncio
async def test_expired_worker_lease_is_durably_requeued_and_reclaimed(session_factory) -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    scope, run_id = await _identity_and_run(session_factory)
    handler = RecordingHandler()
    service = _service(session_factory, handler, now=lambda: now)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)
    await service.consume(issued.token, actor=scope)
    repository = SuggestedActionRepository(session_factory)

    first = await repository.claim_for_execution(
        issued.id, now=now, lease_duration=timedelta(seconds=30)
    )
    duplicate = await repository.claim_for_execution(
        issued.id, now=now, lease_duration=timedelta(seconds=30)
    )
    recovered = await repository.recover_expired(now=now + timedelta(seconds=31))
    second = await repository.claim_for_execution(
        issued.id,
        now=now + timedelta(seconds=31),
        lease_duration=timedelta(seconds=30),
    )

    assert first is not None
    assert duplicate is None
    assert recovered == 1
    assert second is not None
    assert second.attempt_count == 2
    assert not await repository.complete(
        issued.id,
        scope.account_id,
        '{"stale":true}',
        attempt_count=first.attempt_count,
    )
    assert await repository.complete(
        issued.id,
        scope.account_id,
        '{"saved":true}',
        attempt_count=second.attempt_count,
    )


@pytest.mark.asyncio
async def test_same_family_other_account_and_cross_family_actor_cannot_consume(
    session_factory,
) -> None:
    owner, run_id = await _identity_and_run(session_factory, "owner-scope@example.com")
    cross_family, _ = await _identity_and_run(session_factory, "other-family@example.com")
    same_family_other_account = HouseholdScope(cross_family.account_id, owner.household_id)
    handler = RecordingHandler()
    service = _service(session_factory, handler)
    issued = await service.issue(_draft(), actor=owner, source_run_id=run_id)

    with pytest.raises(SuggestedActionNotFoundError):
        await service.consume(issued.token, actor=same_family_other_account)
    with pytest.raises(SuggestedActionNotFoundError):
        await service.consume(issued.token, actor=cross_family)
    assert handler.calls == []
    assert (await service.consume(issued.token, actor=owner)).status == "queued"
    assert (await service.execute_queued(issued.id)).status == "succeeded"
    with pytest.raises(SuggestedActionNotFoundError):
        await service.get_status(issued.id, actor=same_family_other_account)


@pytest.mark.asyncio
async def test_claim_must_match_database_row_and_source_run(session_factory) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    handler = RecordingHandler()
    service = _service(session_factory, handler)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)
    async with session_factory() as session:
        await session.execute(
            update(SuggestedActionRecord)
            .where(SuggestedActionRecord.id == issued.id)
            .values(action_type="create_share")
        )
        await session.commit()

    with pytest.raises(InvalidSuggestedActionError):
        await service.consume(issued.token, actor=scope)
    assert handler.calls == []


@pytest.mark.asyncio
async def test_claim_requires_database_expiry_to_exactly_match_signed_expiry(
    session_factory,
) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    handler = RecordingHandler()
    service = _service(session_factory, handler)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)
    async with session_factory() as session:
        await session.execute(
            update(SuggestedActionRecord)
            .where(SuggestedActionRecord.id == issued.id)
            .values(expires_at=issued.expires_at + timedelta(minutes=5))
        )
        await session.commit()

    with pytest.raises(InvalidSuggestedActionError):
        await service.consume(issued.token, actor=scope)
    assert handler.calls == []


def test_nested_action_argument_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RecipeIngredientCandidate.model_validate({"name": "salt", "private": "secret"})
    with pytest.raises(ValidationError):
        RecipeStepCandidate.model_validate({"number": 1, "text": "Stir", "private": "secret"})
    with pytest.raises(ValidationError):
        PlanSlot.model_validate({"day": "2026-07-20", "slot": "dinner", "private": "secret"})


@pytest.mark.asyncio
async def test_tampered_persisted_arguments_are_failed_without_handler_dispatch(
    session_factory,
) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    handler = RecordingHandler()
    service = _service(session_factory, handler)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)
    async with session_factory() as session:
        await session.execute(
            update(SuggestedActionRecord)
            .where(SuggestedActionRecord.id == issued.id)
            .values(arguments_json='{"name":"Soup","account_id":"forged"}')
        )
        await session.commit()

    assert (await service.consume(issued.token, actor=scope)).status == "queued"
    with pytest.raises(InvalidSuggestedActionError):
        await service.execute_queued(issued.id)

    async with session_factory() as session:
        record = await session.get(SuggestedActionRecord, issued.id)
    assert record is not None
    assert record.execution_status == "failed"
    assert record.error_code == "arguments_invalid"
    assert handler.calls == []


@pytest.mark.asyncio
async def test_handler_failure_is_audited_consumed_and_not_replayed(session_factory) -> None:
    scope, run_id = await _identity_and_run(session_factory)
    handler = RecordingHandler(failure=RuntimeError("private database password"))
    service = _service(session_factory, handler)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)

    assert (await service.consume(issued.token, actor=scope)).status == "queued"
    for _ in range(3):
        with pytest.raises(ActionExecutionError, match="execution failed"):
            await service.execute_queued(issued.id)
    with pytest.raises(SuggestedActionConflictError):
        await service.consume(issued.token, actor=scope)

    async with session_factory() as session:
        record = await session.get(SuggestedActionRecord, issued.id)
    assert record is not None
    assert record.consumed_at is not None
    assert record.consumed_by_account_id == scope.account_id
    assert record.execution_status == "failed"
    assert record.error_code == "handler_failed"
    assert "password" not in (record.error_code or "")
    assert handler.calls == [issued.id, issued.id, issued.id]


TEST_DATABASE_URL_ENV = "RECIPE_AGENT_TEST_DATABASE_URL"


@pytest_asyncio.fixture
async def postgres_action_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not configured")
    schema_name = f"action_test_{uuid4().hex}"
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(sync_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": f"{schema_name},public"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
        yield factory
    finally:
        await engine.dispose()
        with psycopg.connect(sync_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.mark.asyncio
async def test_postgres_simultaneous_clicks_queue_exactly_once(postgres_action_factory) -> None:
    scope, run_id = await _identity_and_run(postgres_action_factory, "race@example.com")
    handler = RecordingHandler()
    service = _service(postgres_action_factory, handler)
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)

    results = await asyncio.gather(
        service.consume(issued.token, actor=scope),
        service.consume(issued.token, actor=scope),
        return_exceptions=True,
    )

    assert sum(getattr(result, "status", None) == "queued" for result in results) == 1
    assert sum(isinstance(result, SuggestedActionConflictError) for result in results) == 1
    assert handler.calls == []
    assert (await service.execute_queued(issued.id)).status == "succeeded"
    assert handler.calls == [issued.id]


@pytest.mark.asyncio
async def test_postgres_simultaneous_mutation_retries_return_one_receipt(
    postgres_action_factory,
) -> None:
    scope, run_id = await _identity_and_run(postgres_action_factory, "mutation-race@example.com")
    service = _service(postgres_action_factory, RecordingHandler())
    issued = await service.issue(_draft(), actor=scope, source_run_id=run_id)
    handler = SaveRecipeMutationHandler(RecipeRepository(postgres_action_factory))
    arguments = SaveRecipeArguments(name="Soup", ingredients=(), steps=())

    first, second = await asyncio.gather(
        handler.execute(actor=scope, arguments=arguments, action_id=issued.id),
        handler.execute(actor=scope, arguments=arguments, action_id=issued.id),
    )

    async with postgres_action_factory() as session:
        recipe_count = await session.scalar(select(func.count()).select_from(Recipe))
    assert first == second
    assert recipe_count == 1
