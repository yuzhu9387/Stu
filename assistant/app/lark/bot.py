from __future__ import annotations
from typing import Optional, Dict, Any

from app.lark.cards import CardBuilder
from app.lark.client import LarkClient
from app.lark.webhook import LarkEvent


class LarkBot:
    """Thin pass-through: parses LarkEvent and delegates to caller.

    The webhook layer is now responsible for resolving lark_user_id → user_id
    and invoking ConversationOrchestrator. LarkBot's only job is to carry
    LarkClient and provide a few view helpers for card responses.
    """

    def __init__(self, client: LarkClient):
        self.client = client

    async def handle_card_action(self, event: LarkEvent) -> Dict[str, Any]:
        return {"user_id": event.user_id, "action": event.action_value, "handled": True}

    @staticmethod
    def text_card(text: str) -> Optional[Dict[str, Any]]:
        return CardBuilder.question_card(title="Assistant", question=text)
