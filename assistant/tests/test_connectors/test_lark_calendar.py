import pytest
from unittest.mock import AsyncMock
from app.connectors.lark_calendar import LarkCalendarConnector

@pytest.mark.asyncio
async def test_sync():
    mock = AsyncMock()
    mock.get_calendar_events = AsyncMock(return_value=[
        {"event_id": "e1", "summary": "Standup", "start_time": "2026-05-12T10:00:00+08:00", "end_time": "2026-05-12T10:30:00+08:00"},
        {"event_id": "e2", "summary": "Review", "start_time": "2026-05-12T14:00:00+08:00", "end_time": "2026-05-12T15:00:00+08:00"},
    ])
    r = await LarkCalendarConnector(client=mock).sync(user_id=1)
    assert r.items_synced == 2

@pytest.mark.asyncio
async def test_on_event_created():
    c = LarkCalendarConnector(client=AsyncMock())
    r = await c.on_event({"type": "calendar.event.created", "event": {"event_id": "e_new", "summary": "New", "start_time": "2026-05-12T16:00:00+08:00", "end_time": "2026-05-12T17:00:00+08:00"}, "user_id": 1})
    assert r is not None and r.items_created == 1

def test_parse_event():
    c = LarkCalendarConnector(client=AsyncMock())
    ev = c.parse_event({"event_id": "e1", "summary": "Test", "start_time": "2026-05-12T10:00:00+08:00", "end_time": "2026-05-12T10:30:00+08:00"})
    assert ev["title"] == "Test"

def test_name():
    assert LarkCalendarConnector(client=AsyncMock()).name == "lark_calendar"
