from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from recipe_agent.domain.identity.service import IdentityService
from recipe_agent.infrastructure.db.base import Base


@pytest.fixture
def client_factory() -> Iterator[Callable[[FastAPI], TestClient]]:
    """Run each test client's lifespan and dispose its runtime before its loop closes."""
    with ExitStack() as clients:

        def create_client(app: FastAPI) -> TestClient:
            return clients.enter_context(TestClient(app))

        yield create_client


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def identity_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> IdentityService:
    return IdentityService(session_factory=session_factory)
