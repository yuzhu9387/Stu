"""Isolated PostgreSQL schema per test, matching test_repository_postgres.py.

Deliberately named apart from the shared `session_factory` in tests/conftest.py,
which is SQLite; shadowing it would drag every kitchen test onto PostgreSQL.

Every model must be imported so `Base.metadata` is complete; otherwise
`create_all` silently omits tables that another module happened not to import.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from recipe_agent.domain.feedback import models as _feedback  # noqa: F401
from recipe_agent.domain.identity import models as _identity  # noqa: F401
from recipe_agent.domain.identity import preferences as _preferences  # noqa: F401
from recipe_agent.domain.identity.models import Account, Household
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen import models as _kitchen  # noqa: F401
from recipe_agent.domain.kitchen import schema as _kitchen_schema  # noqa: F401
from recipe_agent.domain.planning import models as _planning  # noqa: F401
from recipe_agent.domain.recipes import models as _recipes  # noqa: F401
from recipe_agent.domain.sharing import models as _sharing  # noqa: F401
from recipe_agent.infrastructure.db import outbox as _outbox  # noqa: F401
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.jobs import kitchen as _kitchen_jobs  # noqa: F401
from recipe_agent.infrastructure.jobs import kitchen_ai_tasks as _kitchen_ai_tasks  # noqa: F401
from recipe_agent.infrastructure.lark import events as _lark  # noqa: F401


@pytest_asyncio.fixture
async def relational_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RECIPE_AGENT_TEST_DATABASE_URL is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("RECIPE_AGENT_TEST_DATABASE_URL must use postgresql+asyncpg://")
    schema = f"kitchen_rel_{uuid4().hex}"
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(sync_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"search_path": f"{schema},public"}}
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        with psycopg.connect(sync_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest_asyncio.fixture
async def relational_scope(
    relational_sessions: async_sessionmaker[AsyncSession],
) -> HouseholdScope:
    """A real account owning a real household.

    Returning the scope rather than a bare id keeps callers from pairing a
    household with itself as the actor, which silently drops `actorId`.
    """
    account_id, household_id = uuid4(), uuid4()
    async with relational_sessions() as session, session.begin():
        session.add(Account(id=account_id, email=f"{account_id}@example.com"))
        await session.flush()
        session.add(Household(id=household_id, owner_account_id=account_id))
    return HouseholdScope(account_id=account_id, household_id=household_id)


@pytest_asyncio.fixture
async def relational_household(relational_scope: HouseholdScope) -> UUID:
    return relational_scope.household_id
