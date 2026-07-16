import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from recipe_agent.domain.conversation.read_tools import ReadOnlyToolRegistry  # noqa: F401
from recipe_agent.domain.identity.models import Account, FamilyMembership, Household
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.recipes.contracts import RecipeCandidate
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.infrastructure.db.base import Base

TEST_DATABASE_URL_ENV = "RECIPE_AGENT_TEST_DATABASE_URL"


@pytest_asyncio.fixture
async def postgres_read_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(f"{TEST_DATABASE_URL_ENV} must use postgresql+asyncpg://")

    schema_name = f"read_tools_test_{uuid4().hex}"
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


async def test_postgres_concurrent_owner_and_family_queries_do_not_cross_scope(
    postgres_read_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_read_factory() as session:
        alice = Account(email="alice-pg@example.com")
        bob = Account(email="bob-pg@example.com")
        outsider = Account(email="outsider-pg@example.com")
        session.add_all([alice, bob, outsider])
        await session.flush()
        family = Household(owner_account_id=alice.id)
        other_family = Household(owner_account_id=outsider.id)
        session.add_all([family, other_family])
        await session.flush()
        session.add_all(
            [
                FamilyMembership(account_id=alice.id, household_id=family.id, role="owner"),
                FamilyMembership(account_id=bob.id, household_id=family.id, role="member"),
                FamilyMembership(
                    account_id=outsider.id,
                    household_id=other_family.id,
                    role="owner",
                ),
            ]
        )
        await session.commit()

    repository = RecipeRepository(postgres_read_factory)
    await repository.create(
        alice.id, family.id, RecipeCandidate(name="Tomato Alice", ingredients=(), steps=())
    )
    await repository.create(
        bob.id, family.id, RecipeCandidate(name="Tomato Bob", ingredients=(), steps=())
    )
    await repository.create(
        outsider.id,
        other_family.id,
        RecipeCandidate(name="Tomato Outsider", ingredients=(), steps=()),
    )

    alice_owned, family_rows, outsider_rows = await asyncio.gather(
        repository.search_owned(HouseholdScope(alice.id, family.id), "tomato"),
        repository.search_family(HouseholdScope(alice.id, family.id), "tomato"),
        repository.search_family(HouseholdScope(outsider.id, other_family.id), "tomato"),
    )

    assert {row.owner_account_id for row in alice_owned} == {alice.id}
    assert {row.owner_account_id for row in family_rows} == {alice.id, bob.id}
    assert {row.owner_account_id for row in outsider_rows} == {outsider.id}
