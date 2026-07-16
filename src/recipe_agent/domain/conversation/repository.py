"""Transactional persistence for private conversations and agent runs."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast, overload
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.contracts import (
    AgentRunView,
    ConversationCommand,
    RunStatus,
)
from recipe_agent.domain.identity.models import AgentRun, Conversation, ConversationMessage
from recipe_agent.infrastructure.db.outbox import OutboxRepository

AGENT_RUN_REQUESTED_TOPIC = "agent.run.requested"


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
            if command.conversation_id is not None:
                await self._require_owned_conversation(session, command)
            existing = await self._find_idempotent(session, command)
            if existing is not None:
                return _view(existing), False

            try:
                async with session.begin_nested():
                    conversation = await self._resolve_conversation(session, command)
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

    async def _resolve_conversation(
        self, session: AsyncSession, command: ConversationCommand
    ) -> Conversation:
        if command.conversation_id is None:
            conversation = Conversation(
                household_id=command.household_id,
                owner_account_id=command.account_id,
                transport=command.transport,
            )
            session.add(conversation)
            await session.flush()
            return conversation

        return await self._require_owned_conversation(session, command)

    async def _require_owned_conversation(
        self, session: AsyncSession, command: ConversationCommand
    ) -> Conversation:
        existing_conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == command.conversation_id,
                Conversation.owner_account_id == command.account_id,
                Conversation.household_id == command.household_id,
            )
        )
        if existing_conversation is None:
            raise ConversationNotFoundError("Conversation not found")
        return existing_conversation


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
