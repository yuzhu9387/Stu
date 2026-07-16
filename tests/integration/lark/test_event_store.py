import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxEvent, OutboxRepository
from recipe_agent.infrastructure.lark.events import (
    DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS,
    LarkDeliveryAttemptsExhaustedError,
    LarkDeliveryInProgressError,
    LarkEventLease,
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

    lease = await store.reserve("evt_same", "a" * 64)
    assert isinstance(lease, LarkEventLease)
    assert await store.accept(
        "evt_same",
        "a" * 64,
        "message_submitted",
        attempt_count=lease.attempt_count,
    )
    assert await store.reserve("evt_same", "a" * 64) == "duplicate"


@pytest.mark.asyncio
async def test_event_id_substitution_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SqlLarkEventStore(session_factory)
    assert isinstance(await store.reserve("evt_same", "a" * 64), LarkEventLease)

    with pytest.raises(LarkEventSubstitutionError):
        await store.reserve("evt_same", "b" * 64)


@pytest.mark.asyncio
async def test_live_event_lease_is_busy_so_provider_can_retry_after_a_crash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SqlLarkEventStore(session_factory)
    start = datetime(2026, 7, 15, tzinfo=UTC)
    assert isinstance(
        await store.reserve("evt_crash", "a" * 64, now=start, lease_duration=timedelta(seconds=5)),
        LarkEventLease,
    )
    assert (
        await store.reserve(
            "evt_crash",
            "a" * 64,
            now=start + timedelta(seconds=4),
            lease_duration=timedelta(seconds=5),
        )
        == "busy"
    )
    assert isinstance(
        await store.reserve(
            "evt_crash",
            "a" * 64,
            now=start + timedelta(seconds=6),
            lease_duration=timedelta(seconds=5),
        ),
        LarkEventLease,
    )


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

    first = await store.claim(event_id, now=start, lease_duration=timedelta(seconds=5))
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


@pytest.mark.asyncio
async def test_stale_event_attempt_cannot_finalize_after_lease_takeover(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SqlLarkEventStore(session_factory)
    start = datetime(2026, 7, 15, tzinfo=UTC)
    first = await store.reserve(
        "evt_stale", "a" * 64, now=start, lease_duration=timedelta(seconds=5)
    )
    second = await store.reserve(
        "evt_stale",
        "a" * 64,
        now=start + timedelta(seconds=6),
        lease_duration=timedelta(seconds=5),
    )
    assert isinstance(first, LarkEventLease)
    assert isinstance(second, LarkEventLease)
    assert second.attempt_count == first.attempt_count + 1
    assert not await store.accept(
        "evt_stale",
        "a" * 64,
        "stale",
        attempt_count=first.attempt_count,
        now=start + timedelta(seconds=7),
    )
    assert await store.accept(
        "evt_stale",
        "a" * 64,
        "fresh",
        attempt_count=second.attempt_count,
        now=start + timedelta(seconds=7),
    )


@pytest.mark.asyncio
async def test_stale_identity_response_cannot_publish_before_fresh_acceptance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SqlLarkEventStore(session_factory)
    start = datetime(2026, 7, 15, tzinfo=UTC)
    first = await store.reserve(
        "evt_identity", "a" * 64, now=start, lease_duration=timedelta(seconds=5)
    )
    second = await store.reserve("evt_identity", "a" * 64, now=start + timedelta(seconds=6))
    assert isinstance(first, LarkEventLease)
    assert isinstance(second, LarkEventLease)
    assert not await store.accept_with_delivery(
        "evt_identity",
        "a" * 64,
        "stale",
        attempt_count=first.attempt_count,
        topic="lark.stale",
        payload={"chat_id": "oc_test"},
        dedupe_key="event:evt_identity:identity_response",
        now=start + timedelta(seconds=7),
    )
    assert await store.accept_with_delivery(
        "evt_identity",
        "a" * 64,
        "fresh",
        attempt_count=second.attempt_count,
        topic="lark.fresh",
        payload={"chat_id": "oc_test"},
        dedupe_key="event:evt_identity:identity_response",
        now=start + timedelta(seconds=7),
    )
    async with session_factory() as session:
        topics = tuple(await session.scalars(select(OutboxEvent.topic)))
    assert topics == ("lark.fresh",)


@pytest.mark.asyncio
async def test_delivery_last_failed_attempt_is_persisted_as_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        event = await add_lark_delivery_intent(
            session,
            OutboxRepository(),
            topic="lark.test",
            payload={"chat_id": "oc_test"},
            dedupe_key="delivery:exhausted",
        )
        event_id = event.id
    store = SqlLarkDeliveryStore(session_factory)
    start = datetime(2026, 7, 15, tzinfo=UTC)
    for attempt in range(1, DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS + 1):
        claimed = await store.claim(event_id, now=start + timedelta(seconds=attempt))
        assert claimed is not None and claimed.attempt_count == attempt
        assert await store.mark_retry(
            event_id,
            attempt_count=attempt,
            error_code="LarkAPIError",
        )

    with pytest.raises(LarkDeliveryAttemptsExhaustedError):
        await store.claim(event_id, now=start + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_live_final_delivery_attempt_cannot_be_terminal_failed_by_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        event = await add_lark_delivery_intent(
            session,
            OutboxRepository(),
            topic="lark.test",
            payload={"chat_id": "oc_test"},
            dedupe_key="delivery:live-final",
        )
        event_id = event.id
    store = SqlLarkDeliveryStore(session_factory)
    start = datetime(2026, 7, 15, tzinfo=UTC)
    for attempt in range(1, DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS):
        claimed = await store.claim(event_id, now=start + timedelta(seconds=attempt))
        assert claimed is not None
        assert await store.mark_retry(event_id, attempt_count=attempt, error_code="LarkAPIError")
    final = await store.claim(
        event_id,
        now=start + timedelta(seconds=10),
        lease_duration=timedelta(seconds=30),
    )
    assert final is not None
    assert final.attempt_count == DEFAULT_LARK_DELIVERY_MAX_ATTEMPTS
    with pytest.raises(LarkDeliveryInProgressError):
        await store.claim(event_id, now=start + timedelta(seconds=11))
    assert await store.mark_delivered(
        event_id,
        attempt_count=final.attempt_count,
        now=start + timedelta(seconds=12),
    )


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

    assert sum(isinstance(result, LarkEventLease) for result in results) == 1
    assert sum(isinstance(result, LarkEventSubstitutionError) for result in results) == 1
