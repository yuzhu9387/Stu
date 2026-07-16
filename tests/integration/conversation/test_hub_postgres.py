import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.repository import AgentRunRepository
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.models import AgentRun, Conversation, ConversationMessage
from recipe_agent.domain.identity.service import IdentityService
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxEvent

TEST_DATABASE_URL_ENV = "RECIPE_AGENT_TEST_DATABASE_URL"


@pytest_asyncio.fixture
async def postgres_conversation_runtime() -> AsyncIterator[
    tuple[IdentityService, async_sessionmaker[AsyncSession]]
]:
    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(f"{TEST_DATABASE_URL_ENV} must use postgresql+asyncpg://")

    schema_name = f"conversation_test_{uuid4().hex}"
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(sync_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))

    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": f"{schema_name},public"}},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
        yield IdentityService(session_factory=session_factory), session_factory
    finally:
        await engine.dispose()
        with psycopg.connect(sync_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


async def test_simultaneous_same_key_submission_creates_one_durable_request(
    postgres_conversation_runtime: tuple[IdentityService, async_sessionmaker[AsyncSession]],
) -> None:
    identity, session_factory = postgres_conversation_runtime
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link("concurrent@example.com")).token
    )
    hub = ConversationHub(AgentRunRepository(session_factory))

    def command() -> ConversationCommand:
        return ConversationCommand(
            account_id=authenticated.account.id,
            household_id=authenticated.household.id,
            conversation_id=None,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Submit exactly once",
            transport="web",
            idempotency_key="simultaneous-request-1",
        )

    first_command = command()
    second_command = command()
    assert first_command.run_id != second_command.run_id

    first, second = await asyncio.wait_for(
        asyncio.gather(
            hub.submit_message(first_command),
            hub.submit_message(second_command),
        ),
        timeout=10,
    )

    assert first.id == second.id
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 1
        assert await session.scalar(select(func.count()).select_from(AgentRun)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1


async def test_simultaneous_first_lark_events_share_deterministic_conversation(
    postgres_conversation_runtime: tuple[IdentityService, async_sessionmaker[AsyncSession]],
) -> None:
    identity, session_factory = postgres_conversation_runtime
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link("lark-race@example.com")).token
    )
    hub = ConversationHub(AgentRunRepository(session_factory))
    chat_id = uuid4()
    first_command = ConversationCommand(
        account_id=authenticated.account.id,
        household_id=authenticated.household.id,
        conversation_id=chat_id,
        allow_conversation_creation=True,
        locale=Locale.EN_US,
        message="First simultaneous Lark event",
        transport="lark",
        idempotency_key="lark-simultaneous-1",
    )
    second_command = ConversationCommand(
        account_id=authenticated.account.id,
        household_id=authenticated.household.id,
        conversation_id=chat_id,
        allow_conversation_creation=True,
        locale=Locale.EN_US,
        message="Second simultaneous Lark event",
        transport="lark",
        idempotency_key="lark-simultaneous-2",
    )
    assert first_command.run_id != second_command.run_id

    first, second = await asyncio.wait_for(
        asyncio.gather(
            hub.submit_message(first_command),
            hub.submit_message(second_command),
        ),
        timeout=10,
    )

    assert first.id == first_command.run_id
    assert second.id == second_command.run_id
    assert first.conversation_id == chat_id
    assert second.conversation_id == chat_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 2
        assert await session.scalar(select(func.count()).select_from(AgentRun)) == 2
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 2
