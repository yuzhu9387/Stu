import pytest
from unittest.mock import AsyncMock
from app.lark.bot import LarkBot
from app.lark.client import LarkClient
from app.lark.webhook import LarkEvent


@pytest.mark.asyncio
async def test_bot_handles_card_action():
    mock_client = AsyncMock(spec=LarkClient)
    bot = LarkBot(client=mock_client)
    event = LarkEvent(event_type="card.action.trigger", user_id="user_card", action_value="confirm")
    response = await bot.handle_card_action(event)
    assert response["handled"] is True
