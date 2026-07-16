import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.lark.events import (
    LarkDeliveryInProgressError,
    LarkEventSubstitutionError,
    SqlLarkDeliveryStore,
    SqlLarkEventStore,
    add_lark_delivery_intent,
)


@pytest.mark.asyncio
async def test_event_reservation_is_accepted_once_and_replay_is_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SqlLarkEventStore(session_factory)

    assert await store.reserve("evt_same", "a" * 64) == "acquired"
    await store.accept("evt_same", "a" * 64, "message_submitted")
    assert await store.reserve("evt_same", "a" * 64) == "duplicate"


@pytest.mark.asyncio
async def test_event_id_substitution_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SqlLarkEventStore(session_factory)
    assert await store.reserve("evt_same", "a" * 64) == "acquired"

    with pytest.raises(LarkEventSubstitutionError):
        await store.reserve("evt_same", "b" * 64)


@pytest.mark.asyncio
async def test_delivery_lease_recovers_and_delivered_receipt_is_permanent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        event = await add_lark_delivery_intent(
            session,
            OutboxRepository(),
            topic="lark.test",
            payload={"chat_id": "oc_test"},
            dedupe_key="delivery:test",
        )
        event_id = event.id
    store = SqlLarkDeliveryStore(session_factory)
    start = datetime(2026, 7, 15, tzinfo=UTC)

    first = await store.claim(
        event_id, now=start, lease_duration=timedelta(seconds=5)
    )
    assert first is not None and first.attempt_count == 1
    with pytest.raises(LarkDeliveryInProgressError):
        await store.claim(event_id, now=start + timedelta(seconds=4))
    second = await store.claim(event_id, now=start + timedelta(seconds=6))
    assert second is not None and second.attempt_count == 2
    assert await store.mark_delivered(
        event_id,
        attempt_count=second.attempt_count,
        now=start + timedelta(seconds=7),
    )
    assert await store.claim(event_id, now=start + timedelta(seconds=8)) is None


@pytest_asyncio.fixture
async def postgres_event_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RECIPE_AGENT_TEST_DATABASE_URL is not configured")
    schema_name = f"lark_event_test_{uuid4().hex}"
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
async def test_postgres_concurrent_event_substitution_has_one_winner(
    postgres_event_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = SqlLarkEventStore(postgres_event_factory)
    second = SqlLarkEventStore(postgres_event_factory)

    results = await asyncio.gather(
        first.reserve("evt_race", "a" * 64),
        second.reserve("evt_race", "b" * 64),
        return_exceptions=True,
    )

    assert sum(result == "acquired" for result in results) == 1
    assert sum(isinstance(result, LarkEventSubstitutionError) for result in results) == 1
