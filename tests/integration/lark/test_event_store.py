import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.infrastructure.lark.events import SqlLarkEventStore


@pytest.mark.asyncio
async def test_event_id_is_claimed_once_across_store_instances(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_store = SqlLarkEventStore(session_factory)
    second_store = SqlLarkEventStore(session_factory)

    assert await first_store.claim("evt_same") is True
    assert await second_store.claim("evt_same") is False
