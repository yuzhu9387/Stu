from __future__ import annotations
import logging

from app.config import settings
from app.lark.client import LarkClient

logger = logging.getLogger(__name__)


class LarkMessenger:
    """Thin async wrapper around LarkClient for proactive pushes."""

    def __init__(self, client: LarkClient):
        self.client = client

    async def push(self, lark_user_id: str, text: str) -> bool:
        if settings.proactive_dry_run:
            logger.info("DRY RUN push to %s: %s", lark_user_id, text)
            return True
        try:
            await self.client.send_text(lark_user_id, text)
            return True
        except Exception as e:
            logger.warning("lark push failed for %s: %s", lark_user_id, e)
            return False
