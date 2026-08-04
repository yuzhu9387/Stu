from __future__ import annotations
import logging
from typing import Optional

import voyageai

from app.config import settings

logger = logging.getLogger(__name__)


class VoyageClient:
    """Thin async wrapper around voyageai.AsyncClient.

    Soft-fails: when no API key is configured, embed() returns an empty list.
    Callers must treat an empty list as "skip this item, no error."
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.voyage_api_key
        self._client = (
            voyageai.AsyncClient(api_key=self._api_key) if self._api_key else None
        )

    async def embed(self, text: str) -> list[float]:
        if self._client is None:
            logger.info("voyage_client: no API key configured; returning empty vector")
            return []
        result = await self._client.embed([text], model="voyage-3")
        return result.embeddings[0]
