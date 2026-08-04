from __future__ import annotations
from typing import Optional, Dict, Any, List
from app.connectors.base import BaseConnector, SyncResult
# TODO(spec-2): wire to ConversationOrchestrator
# from app.engines.task_extractor import TaskExtractor


class EmailConnector(BaseConnector):
    def __init__(self):
        # TODO(spec-2): wire to ConversationOrchestrator
        self._extractor = None
        self._pending_tasks: Dict[int, List[Dict[str, Any]]] = {}

    @property
    def name(self) -> str:
        return "email"

    async def sync(self, user_id: int) -> SyncResult:
        return SyncResult(connector=self.name, items_synced=0)

    async def on_event(self, event_data: Dict[str, Any]) -> Optional[SyncResult]:
        # TODO(spec-2): wire to ConversationOrchestrator
        raise NotImplementedError("rewired in spec 2")

    def get_pending_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        return self._pending_tasks.get(user_id, [])
