import asyncio
import os
from collections.abc import AsyncIterator
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

from recipe_agent.domain.identity.models import FamilyMembership, Household
from recipe_agent.domain.identity.service import (
    HouseholdScope,
    IdentityConflictError,
    IdentityService,
)
from recipe_agent.infrastructure.db.base import Base

TEST_DATABASE_URL_ENV = "RECIPE_AGENT_TEST_DATABASE_URL"


@pytest_asyncio.fixture
async def postgres_identity_service() -> AsyncIterator[
    tuple[IdentityService, async_sessionmaker[AsyncSession]]
]:
    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(f"{TEST_DATABASE_URL_ENV} must use postgresql+asyncpg://")

    schema_name = f"identity_test_{uuid4().hex}"
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(sync_url) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )

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
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


@pytest.mark.asyncio
async def test_postgres_family_join_updates_session_and_deletes_source(
    postgres_identity_service,
) -> None:
    service, session_factory = postgres_identity_service
    owner = await service.consume_magic_link(
        (await service.request_magic_link("owner@example.com")).token
    )
    member = await service.consume_magic_link(
        (await service.request_magic_link("member@example.com")).token
    )
    source_household_id = member.household.id
    invite = await service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    membership = await service.accept_family_invite(
        HouseholdScope(member.account.id, source_household_id), invite.code
    )

    assert membership.household_id == owner.household.id
    assert await service.resolve_web_session(member.session_token) == HouseholdScope(
        member.account.id, owner.household.id
    )
    async with session_factory() as session:
        assert await session.get(Household, source_household_id) is None


@pytest.mark.asyncio
async def test_postgres_lark_link_claim_commits(postgres_identity_service) -> None:
    service, _ = postgres_identity_service
    account = await service.consume_magic_link(
        (await service.request_magic_link("lark@example.com")).token
    )
    code = await service.create_lark_link_code(account.account.id)

    identity = await service.link_lark_identity(code.code, "ou_postgres")

    assert identity.account_id == account.account.id
    assert await service.resolve_lark_identity("ou_postgres") == HouseholdScope(
        account.account.id, account.household.id
    )


@pytest.mark.asyncio
async def test_postgres_reciprocal_joins_finish_without_unhandled_db_error(
    postgres_identity_service,
) -> None:
    service, session_factory = postgres_identity_service
    first = await service.consume_magic_link(
        (await service.request_magic_link("first@example.com")).token
    )
    second = await service.consume_magic_link(
        (await service.request_magic_link("second@example.com")).token
    )
    first_invite = await service.create_family_invite(
        HouseholdScope(first.account.id, first.household.id)
    )
    second_invite = await service.create_family_invite(
        HouseholdScope(second.account.id, second.household.id)
    )

    results = await asyncio.wait_for(
        asyncio.gather(
            service.accept_family_invite(
                HouseholdScope(first.account.id, first.household.id),
                second_invite.code,
            ),
            service.accept_family_invite(
                HouseholdScope(second.account.id, second.household.id),
                first_invite.code,
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )

    assert sum(isinstance(result, FamilyMembership) for result in results) == 1, repr(
        results
    )
    assert sum(isinstance(result, IdentityConflictError) for result in results) == 1, repr(
        results
    )
    async with session_factory() as session:
        memberships = (await session.scalars(select(FamilyMembership))).all()
    assert len(memberships) == 2
    assert len({membership.household_id for membership in memberships}) == 1
