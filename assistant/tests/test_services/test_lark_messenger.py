import pytest
from unittest.mock import AsyncMock

from app.lark.client import LarkClient
from app.services.lark_messenger import LarkMessenger


async def test_push_sends_text_via_client(monkeypatch):
    monkeypatch.setattr("app.services.lark_messenger.settings.proactive_dry_run", False)
    client = AsyncMock(spec=LarkClient)
    client.send_text = AsyncMock(return_value={"message_id": "m1"})
    m = LarkMessenger(client)
    await m.push("user_xyz", "hi")
    client.send_text.assert_awaited_once_with("user_xyz", "hi")


async def test_push_dry_run_skips_send(monkeypatch, caplog):
    monkeypatch.setattr("app.services.lark_messenger.settings.proactive_dry_run", True)
    client = AsyncMock(spec=LarkClient)
    m = LarkMessenger(client)
    with caplog.at_level("INFO"):
        await m.push("user_xyz", "hello")
    client.send_text.assert_not_called()
    assert "DRY RUN" in caplog.text or "dry run" in caplog.text


async def test_push_swallows_client_error_and_logs(monkeypatch, caplog):
    monkeypatch.setattr("app.services.lark_messenger.settings.proactive_dry_run", False)
    client = AsyncMock(spec=LarkClient)
    client.send_text = AsyncMock(side_effect=RuntimeError("network"))
    m = LarkMessenger(client)
    with caplog.at_level("WARNING"):
        result = await m.push("user_xyz", "hi")
    assert result is False
    assert "lark push failed" in caplog.text.lower() or "lark" in caplog.text.lower()
