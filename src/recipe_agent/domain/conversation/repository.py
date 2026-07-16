"""Transactional persistence for private conversations and agent runs."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast, overload
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.contracts import (
    AgentRunView,
    ConversationCommand,
    RunStatus,
)
from recipe_agent.domain.identity.models import (
    AgentRun,
    Conversation,
    ConversationMessage,
    SuggestedActionRecord,
)
from recipe_agent.infrastructure.db.outbox import OutboxRepository

AGENT_RUN_REQUESTED_TOPIC = "agent.run.requested"
ACTION_EXECUTION_REQUESTED_TOPIC = "agent.action.requested"


class SuggestedActionRunNotFoundError(LookupError):
    """The source run does not belong to the issuing scope."""


class SuggestedActionAlreadyClaimedError(RuntimeError):
    """The persisted action has already left its pending state."""


class SuggestedActionInvalidRecordError(ValueError):
    """The token claims do not match a live persisted action."""


@dataclass(frozen=True)
class ClaimedSuggestedAction:
    id: UUID
    account_id: UUID
    household_id: UUID
    action_type: str
    arguments_json: str
    attempt_count: int


@dataclass(frozen=True)
class PersistedSuggestedAction:
    id: UUID
    account_id: UUID
    household_id: UUID
    action_type: str
    execution_status: str
    result_json: str | None
    error_code: str | None


class ConversationNotFoundError(LookupError):
    """A conversation is not private to the requesting account and household."""


class AgentRunRepository:
    """Persist messages, runs, and their queue intent in one transaction."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        outbox: OutboxRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox or OutboxRepository()

    async def create_idempotent(self, command: ConversationCommand) -> tuple[AgentRunView, bool]:
        async with self._session_factory() as session, session.begin():
            conversation = await self._resolve_existing_conversation(session, command)
            existing = await self._find_idempotent(session, command)
            if existing is not None:
                return _view(existing), False

            try:
                async with session.begin_nested():
                    if conversation is None:
                        if command.conversation_id is None:
                            conversation = await self._create_conversation(session, command)
                        else:
                            conversation = await self._get_or_create_conversation(session, command)
                    session.add(
                        ConversationMessage(
                            conversation_id=conversation.id,
                            role="user",
                            content=command.message,
                        )
                    )
                    run = AgentRun(
                        id=command.run_id,
                        conversation_id=conversation.id,
                        account_id=command.account_id,
                        household_id=command.household_id,
                        transport=command.transport,
                        idempotency_key=command.idempotency_key,
                        status=RunStatus.QUEUED.value,
                        request_json=_request_json(command),
                    )
                    session.add(run)
                    await session.flush()
                    await self._outbox.add(
                        session,
                        AGENT_RUN_REQUESTED_TOPIC,
                        {"run_id": str(run.id)},
                    )
            except IntegrityError as error:
                existing = await self._find_idempotent(session, command)
                if existing is None:
                    raise error
                return _view(existing), False
            return _view(run), True

    async def get_for_account(
        self,
        run_id: UUID,
        *,
        account_id: UUID,
        household_id: UUID,
    ) -> AgentRunView | None:
        async with self._session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.id == run_id,
                    AgentRun.account_id == account_id,
                    AgentRun.household_id == household_id,
                )
            )
            return None if run is None else _view(run)

    async def claim(self, run_id: UUID) -> AgentRunView | None:
        """Atomically transition a queued run to running."""

        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            run = await session.scalar(
                update(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.status == RunStatus.QUEUED.value)
                .values(status=RunStatus.RUNNING.value, started_at=now)
                .returning(AgentRun)
                .execution_options(synchronize_session=False)
            )
            return None if run is None else _view(run)

    async def complete(
        self, run_id: UUID, response: Mapping[str, JsonValue]
    ) -> AgentRunView | None:
        """Complete a running run once; terminal runs are unchanged."""

        return await self._finish(
            run_id,
            status=RunStatus.COMPLETED,
            response_json=json.dumps(response, ensure_ascii=False, separators=(",", ":")),
            error_code=None,
        )

    async def fail(self, run_id: UUID, error_code: str) -> AgentRunView | None:
        """Fail a running run once without persisting private exception text."""

        return await self._finish(
            run_id,
            status=RunStatus.FAILED,
            response_json=None,
            error_code=error_code,
        )

    async def _finish(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        response_json: str | None,
        error_code: str | None,
    ) -> AgentRunView | None:
        async with self._session_factory() as session, session.begin():
            run = await session.scalar(
                update(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.status == RunStatus.RUNNING.value)
                .values(
                    status=status.value,
                    response_json=response_json,
                    error_code=error_code,
                    completed_at=datetime.now(UTC),
                )
                .returning(AgentRun)
                .execution_options(synchronize_session=False)
            )
            return None if run is None else _view(run)

    async def _find_idempotent(
        self, session: AsyncSession, command: ConversationCommand
    ) -> AgentRun | None:
        return cast(
            AgentRun | None,
            await session.scalar(
                select(AgentRun).where(
                    AgentRun.account_id == command.account_id,
                    AgentRun.transport == command.transport,
                    AgentRun.idempotency_key == command.idempotency_key,
                )
            ),
        )

    async def _resolve_existing_conversation(
        self, session: AsyncSession, command: ConversationCommand
    ) -> Conversation | None:
        if command.conversation_id is None:
            if not command.allow_conversation_creation:
                raise ConversationNotFoundError("Conversation not found")
            return None

        conversation = await session.get(Conversation, command.conversation_id)
        if conversation is None:
            if command.allow_conversation_creation:
                return None
            raise ConversationNotFoundError("Conversation not found")
        self._validate_conversation_ownership(conversation, command)
        return conversation

    async def _get_or_create_conversation(
        self, session: AsyncSession, command: ConversationCommand
    ) -> Conversation:
        try:
            async with session.begin_nested():
                return await self._create_conversation(session, command)
        except IntegrityError as error:
            conversation = await session.get(
                Conversation,
                command.conversation_id,
                populate_existing=True,
            )
            if conversation is None:
                raise error
            self._validate_conversation_ownership(conversation, command)
            return conversation

    def _validate_conversation_ownership(
        self, conversation: Conversation, command: ConversationCommand
    ) -> None:
        if (
            conversation.owner_account_id != command.account_id
            or conversation.household_id != command.household_id
        ):
            raise ConversationNotFoundError("Conversation not found")

    async def _create_conversation(
        self, session: AsyncSession, command: ConversationCommand
    ) -> Conversation:
        conversation = Conversation(
            household_id=command.household_id,
            owner_account_id=command.account_id,
            transport=command.transport,
        )
        if command.conversation_id is not None:
            conversation.id = command.conversation_id
        session.add(conversation)
        await session.flush()
        return conversation


class SuggestedActionRepository:
    """Persist and atomically claim signed suggested-action intents."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        outbox: OutboxRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox or OutboxRepository()

    async def create(
        self,
        *,
        action_id: UUID,
        token_hash: str,
        source_run_id: UUID,
        account_id: UUID,
        household_id: UUID,
        action_type: str,
        arguments_json: str,
        expires_at: datetime,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            source_run = await session.scalar(
                select(AgentRun.id).where(
                    AgentRun.id == source_run_id,
                    AgentRun.account_id == account_id,
                    AgentRun.household_id == household_id,
                )
            )
            if source_run is None:
                raise SuggestedActionRunNotFoundError("Source run not found")
            session.add(
                SuggestedActionRecord(
                    id=action_id,
                    token_hash=token_hash,
                    run_id=source_run_id,
                    account_id=account_id,
                    household_id=household_id,
                    action_type=action_type,
                    arguments_json=arguments_json,
                    expires_at=expires_at,
                    execution_status="pending",
                )
            )

    async def queue_once(
        self,
        *,
        token_hash: str,
        action_id: UUID,
        source_run_id: UUID,
        account_id: UUID,
        household_id: UUID,
        action_type: str,
        claim_expires_at: datetime,
        now: datetime,
    ) -> ClaimedSuggestedAction:
        async with self._session_factory() as session, session.begin():
            record = await session.scalar(
                update(SuggestedActionRecord)
                .where(
                    SuggestedActionRecord.id == action_id,
                    SuggestedActionRecord.token_hash == token_hash,
                    SuggestedActionRecord.run_id == source_run_id,
                    SuggestedActionRecord.account_id == account_id,
                    SuggestedActionRecord.household_id == household_id,
                    SuggestedActionRecord.action_type == action_type,
                    SuggestedActionRecord.expires_at == claim_expires_at,
                    SuggestedActionRecord.consumed_at.is_(None),
                    SuggestedActionRecord.execution_status == "pending",
                    SuggestedActionRecord.expires_at > now,
                )
                .values(
                    consumed_at=now,
                    consumed_by_account_id=account_id,
                    execution_status="queued",
                )
                .returning(SuggestedActionRecord)
                .execution_options(synchronize_session=False)
            )
            if record is not None:
                await self._outbox.add(
                    session,
                    ACTION_EXECUTION_REQUESTED_TOPIC,
                    {"action_id": str(record.id)},
                )
                return ClaimedSuggestedAction(
                    id=record.id,
                    account_id=record.account_id,
                    household_id=record.household_id,
                    action_type=record.action_type,
                    arguments_json=record.arguments_json,
                    attempt_count=record.attempt_count,
                )
            existing = await session.scalar(
                select(SuggestedActionRecord).where(SuggestedActionRecord.token_hash == token_hash)
            )
            if existing is None:
                raise SuggestedActionInvalidRecordError("Suggested action is invalid")
            if existing.consumed_at is not None or existing.execution_status != "pending":
                raise SuggestedActionAlreadyClaimedError("Suggested action was already consumed")
            if _as_utc(existing.expires_at) <= now:
                raise SuggestedActionInvalidRecordError("Suggested action is expired")
            raise SuggestedActionInvalidRecordError("Suggested action claims do not match")

    async def claim_for_execution(
        self,
        action_id: UUID,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimedSuggestedAction | None:
        lease_expires_at = now + lease_duration
        async with self._session_factory() as session, session.begin():
            record = await session.scalar(
                update(SuggestedActionRecord)
                .where(
                    SuggestedActionRecord.id == action_id,
                    or_(
                        SuggestedActionRecord.execution_status == "queued",
                        (
                            (SuggestedActionRecord.execution_status == "executing")
                            & (SuggestedActionRecord.lease_expires_at <= now)
                        ),
                    ),
                )
                .values(
                    execution_status="executing",
                    lease_expires_at=lease_expires_at,
                    attempt_count=SuggestedActionRecord.attempt_count + 1,
                    error_code=None,
                )
                .returning(SuggestedActionRecord)
                .execution_options(synchronize_session=False)
            )
            if record is None:
                return None
            return ClaimedSuggestedAction(
                id=record.id,
                account_id=record.account_id,
                household_id=record.household_id,
                action_type=record.action_type,
                arguments_json=record.arguments_json,
                attempt_count=record.attempt_count,
            )

    async def recover_expired(self, *, now: datetime, limit: int = 100) -> int:
        async with self._session_factory() as session, session.begin():
            expired_ids = tuple(
                await session.scalars(
                    select(SuggestedActionRecord.id)
                    .where(
                        SuggestedActionRecord.execution_status == "executing",
                        SuggestedActionRecord.lease_expires_at <= now,
                    )
                    .order_by(SuggestedActionRecord.lease_expires_at)
                    .limit(limit)
                )
            )
            recovered = 0
            for action_id in expired_ids:
                recovered_id = await session.scalar(
                    update(SuggestedActionRecord)
                    .where(
                        SuggestedActionRecord.id == action_id,
                        SuggestedActionRecord.execution_status == "executing",
                        SuggestedActionRecord.lease_expires_at <= now,
                    )
                    .values(execution_status="queued", lease_expires_at=None)
                    .returning(SuggestedActionRecord.id)
                    .execution_options(synchronize_session=False)
                )
                if recovered_id is None:
                    continue
                await self._outbox.add(
                    session,
                    ACTION_EXECUTION_REQUESTED_TOPIC,
                    {"action_id": str(recovered_id)},
                )
                recovered += 1
            return recovered

    async def get_for_actor(
        self,
        action_id: UUID,
        *,
        account_id: UUID,
        household_id: UUID,
    ) -> PersistedSuggestedAction | None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(SuggestedActionRecord).where(
                    SuggestedActionRecord.id == action_id,
                    SuggestedActionRecord.account_id == account_id,
                    SuggestedActionRecord.household_id == household_id,
                )
            )
            if record is None:
                return None
            return PersistedSuggestedAction(
                id=record.id,
                account_id=record.account_id,
                household_id=record.household_id,
                action_type=record.action_type,
                execution_status=record.execution_status,
                result_json=record.result_json,
                error_code=record.error_code,
            )

    async def complete(
        self,
        action_id: UUID,
        actor_account_id: UUID,
        result_json: str,
        *,
        attempt_count: int,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            completed_id = await session.scalar(
                update(SuggestedActionRecord)
                .where(
                    SuggestedActionRecord.id == action_id,
                    SuggestedActionRecord.consumed_by_account_id == actor_account_id,
                    SuggestedActionRecord.execution_status == "executing",
                    SuggestedActionRecord.attempt_count == attempt_count,
                )
                .values(
                    execution_status="succeeded",
                    lease_expires_at=None,
                    result_json=result_json,
                    error_code=None,
                )
                .returning(SuggestedActionRecord.id)
                .execution_options(synchronize_session=False)
            )
            return completed_id is not None

    async def retry_or_fail(
        self,
        action_id: UUID,
        actor_account_id: UUID,
        error_code: str,
        *,
        attempt_count: int,
        max_attempts: int,
    ) -> str:
        async with self._session_factory() as session, session.begin():
            record = await session.scalar(
                select(SuggestedActionRecord).where(
                    SuggestedActionRecord.id == action_id,
                    SuggestedActionRecord.consumed_by_account_id == actor_account_id,
                    SuggestedActionRecord.execution_status == "executing",
                    SuggestedActionRecord.attempt_count == attempt_count,
                )
            )
            if record is None:
                return "unchanged"
            if record.attempt_count >= max_attempts:
                record.execution_status = "failed"
                record.lease_expires_at = None
                record.result_json = None
                record.error_code = error_code
                return "failed"
            record.execution_status = "queued"
            record.lease_expires_at = None
            record.error_code = error_code
            await self._outbox.add(
                session,
                ACTION_EXECUTION_REQUESTED_TOPIC,
                {"action_id": str(action_id)},
            )
            return "queued"

    async def fail(
        self,
        action_id: UUID,
        actor_account_id: UUID,
        error_code: str,
        *,
        attempt_count: int,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            failed_id = await session.scalar(
                update(SuggestedActionRecord)
                .where(
                    SuggestedActionRecord.id == action_id,
                    SuggestedActionRecord.consumed_by_account_id == actor_account_id,
                    SuggestedActionRecord.execution_status == "executing",
                    SuggestedActionRecord.attempt_count == attempt_count,
                )
                .values(
                    execution_status="failed",
                    lease_expires_at=None,
                    result_json=None,
                    error_code=error_code,
                )
                .returning(SuggestedActionRecord.id)
                .execution_options(synchronize_session=False)
            )
            return failed_id is not None


def _request_json(command: ConversationCommand) -> str:
    return json.dumps(
        {
            "locale": command.locale.value,
            "message": command.message,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _view(run: AgentRun) -> AgentRunView:
    response: dict[str, Any] | None = None
    if run.response_json is not None:
        decoded = json.loads(run.response_json)
        if not isinstance(decoded, dict):
            raise TypeError("Agent run response must be an object")
        response = decoded
    return AgentRunView(
        id=run.id,
        conversation_id=run.conversation_id,
        account_id=run.account_id,
        household_id=run.household_id,
        transport=run.transport,
        status=RunStatus(run.status),
        response=response,
        error_code=run.error_code,
        created_at=_as_utc(run.created_at),
        started_at=_as_utc(run.started_at),
        completed_at=_as_utc(run.completed_at),
    )


@overload
def _as_utc(value: datetime) -> datetime: ...


@overload
def _as_utc(value: None) -> None: ...


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
