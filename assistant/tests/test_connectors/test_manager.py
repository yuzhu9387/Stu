import pytest
from unittest.mock import AsyncMock
from app.connectors.manager import ConnectorManager
from app.connectors.base import SyncResult

@pytest.mark.asyncio
async def test_sync_all():
    m1 = AsyncMock(); m1.name = "a"; m1.sync = AsyncMock(return_value=SyncResult(connector="a", items_synced=3))
    m2 = AsyncMock(); m2.name = "b"; m2.sync = AsyncMock(return_value=SyncResult(connector="b", items_synced=5))
    results = await ConnectorManager(connectors=[m1, m2]).sync_all(user_id=1)
    assert len(results) == 2

@pytest.mark.asyncio
async def test_sync_one():
    m = AsyncMock(); m.name = "lark_calendar"; m.sync = AsyncMock(return_value=SyncResult(connector="lark_calendar", items_synced=2))
    r = await ConnectorManager(connectors=[m]).sync_one("lark_calendar", user_id=1)
    assert r.items_synced == 2

@pytest.mark.asyncio
async def test_sync_unknown():
    assert await ConnectorManager(connectors=[]).sync_one("x", user_id=1) is None
