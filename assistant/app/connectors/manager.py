from __future__ import annotations
from typing import Optional, List
from app.connectors.base import BaseConnector, SyncResult


class ConnectorManager:
    def __init__(self, connectors: List[BaseConnector]):
        self._connectors = {c.name: c for c in connectors}

    async def sync_all(self, user_id: int) -> List[SyncResult]:
        return [await c.sync(user_id) for c in self._connectors.values()]

    async def sync_one(self, name: str, user_id: int) -> Optional[SyncResult]:
        c = self._connectors.get(name)
        return await c.sync(user_id) if c else None

    def get_connector(self, name: str) -> Optional[BaseConnector]:
        return self._connectors.get(name)
