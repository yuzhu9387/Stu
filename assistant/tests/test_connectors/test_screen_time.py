import pytest
from datetime import date
from app.connectors.screen_time import ScreenTimeConnector

@pytest.mark.asyncio
async def test_ingest():
    r = await ScreenTimeConnector().on_event({"user_id": 1, "date": "2026-05-12", "entries": [{"app": "WeChat", "minutes": 90, "category": "social"}, {"app": "VS Code", "minutes": 240, "category": "productivity"}]})
    assert r.items_synced == 2

@pytest.mark.asyncio
async def test_summary():
    c = ScreenTimeConnector()
    await c.on_event({"user_id": 1, "date": "2026-05-12", "entries": [{"app": "WeChat", "minutes": 90, "category": "social"}, {"app": "VS Code", "minutes": 240, "category": "productivity"}]})
    s = c.get_daily_summary(1, date(2026, 5, 12))
    assert s["total_minutes"] == 330 and s["by_category"]["social"] == 90

@pytest.mark.asyncio
async def test_empty():
    assert ScreenTimeConnector().get_daily_summary(1, date(2026, 5, 12))["total_minutes"] == 0

def test_name():
    assert ScreenTimeConnector().name == "screen_time"
