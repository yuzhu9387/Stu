import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.lark.client import LarkClient


@pytest.mark.asyncio
async def test_get_tenant_access_token():
    client = LarkClient(app_id="test_id", app_secret="test_secret")
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": 0, "tenant_access_token": "t-test-token", "expire": 7200}
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response):
        token = await client.get_tenant_access_token()
        assert token == "t-test-token"


@pytest.mark.asyncio
async def test_send_text_message():
    client = LarkClient(app_id="test_id", app_secret="test_secret")
    client._token = "t-test-token"
    client._token_expires_at = 9999999999.0
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": 0, "data": {"message_id": "msg_123"}}
    mock_response.raise_for_status = MagicMock()
    with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await client.send_text("user_123", "Hello!")
        assert result["message_id"] == "msg_123"


@pytest.mark.asyncio
async def test_send_interactive_card():
    client = LarkClient(app_id="test_id", app_secret="test_secret")
    client._token = "t-test-token"
    client._token_expires_at = 9999999999.0
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": 0, "data": {"message_id": "msg_456"}}
    mock_response.raise_for_status = MagicMock()
    card = {"header": {"title": {"tag": "plain_text", "content": "Test"}}, "elements": []}
    with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await client.send_card("user_123", card)
        assert result["message_id"] == "msg_456"


def test_client_creation():
    client = LarkClient(app_id="app_123", app_secret="secret_456")
    assert client._app_id == "app_123"
