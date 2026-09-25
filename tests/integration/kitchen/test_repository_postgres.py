"""Exercise kitchen row locks and retry receipts against real PostgreSQL."""

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

from recipe_agent.domain.identity.service import HouseholdScope, IdentityService
from recipe_agent.domain.kitchen.engine import KitchenError
from recipe_agent.domain.kitchen.models import KitchenOperationReceipt, KitchenWorkspace
from recipe_agent.domain.kitchen.repository import KitchenRepository
from recipe_agent.infrastructure.db.base import Base
from tests.unit.kitchen.test_engine import fixture_state


@pytest_asyncio.fixture
async def postgres_kitchen() -> AsyncIterator[
    tuple[KitchenRepository, HouseholdScope, async_sessionmaker[AsyncSession]]
]:
    database_url = os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RECIPE_AGENT_TEST_DATABASE_URL is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("RECIPE_AGENT_TEST_DATABASE_URL must use postgresql+asyncpg://")
    schema = f"kitchen_test_{uuid4().hex}"
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(sync_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"search_path": f"{schema},public"}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
        identity = IdentityService(session_factory=sessions)
        account = await identity.consume_magic_link(
            (await identity.request_magic_link("kitchen-race@example.com")).token
        )
        scope = HouseholdScope(account.account.id, account.household.id)
        yield KitchenRepository(sessions), scope, sessions
    finally:
        await engine.dispose()
        with psycopg.connect(sync_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def test_concurrent_first_write_retry_has_one_receipt(postgres_kitchen):
    repository, scope, sessions = postgres_kitchen
    command = {
        "type": "tag.save",
        "payload": {"name": "宝宝早餐"},
        "expectedRevision": 0,
        "operationId": "same-first-write",
    }
    first, second = await asyncio.wait_for(
        asyncio.gather(repository.command(scope, command), repository.command(scope, command)),
        timeout=10,
    )
    assert first == second
    assert (await repository.get(scope))["revision"] == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(KitchenOperationReceipt)) == 1


async def test_concurrent_edits_with_same_revision_do_not_overwrite(postgres_kitchen):
    repository, scope, _ = postgres_kitchen
    command = {
        "type": "tag.save",
        "payload": {"name": "existing"},
        "expectedRevision": 0,
        "operationId": "seed",
    }
    await repository.command(scope, command)
    outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(
                repository.command(
                    scope,
                    {
                        **command,
                        "expectedRevision": 1,
                        "operationId": name,
                        "payload": {"name": name},
                    },
                )
                for name in ("breakfast", "dinner")
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    errors = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], KitchenError)
    assert errors[0].status_code == 409
    state = await repository.get(scope)
    assert state["revision"] == 2
    assert len(state["tags"]) == 2
    assert "existing" in state["tags"]


async def test_concurrent_meal_completion_consumes_stock_once(postgres_kitchen):
    repository, scope, sessions = postgres_kitchen
    state = fixture_state()
    state["inventory"][0]["portions"] = 5
    async with sessions() as session, session.begin():
        session.add(
            KitchenWorkspace(
                household_id=scope.household_id, revision=state["revision"], state=state
            )
        )
    command = {
        "type": "meal.status",
        "payload": {"planId": "plan", "mealId": "meal", "status": "completed"},
        "expectedRevision": state["revision"],
        "operationId": "complete-once",
    }
    results = await asyncio.wait_for(
        asyncio.gather(repository.command(scope, command), repository.command(scope, command)),
        timeout=10,
    )
    assert results[0] == results[1]
    saved = await repository.get(scope)
    assert [item["portions"] for item in saved["inventory"]] == [2, 3, 1]
    assert saved["revision"] == state["revision"] + 1
    assert len([entry for entry in saved["audit"] if entry["kind"] == "meal.status"]) == 1
