from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.connectors.base import BaseConnector, SyncResult


class LarkCalendarConnector(BaseConnector):
    def __init__(self, client: Any):
        self._client = client
        self._events_cache: Dict[str, Dict] = {}

    @property
    def name(self) -> str:
        return "lark_calendar"

    async def sync(self, user_id: int) -> SyncResult:
        events = await self._client.get_calendar_events()
        created = updated = 0
        for raw in events:
            ev = self.parse_event(raw)
            eid = ev["calendar_event_id"]
            if eid in self._events_cache:
                updated += 1
            else:
                created += 1
            self._events_cache[eid] = ev
        return SyncResult(connector=self.name, items_synced=len(events), items_created=created, items_updated=updated)

    async def on_event(self, event_data: Dict[str, Any]) -> Optional[SyncResult]:
        etype = event_data.get("type", "")
        raw = event_data.get("event", {})
        if "created" in etype or "changed" in etype:
            ev = self.parse_event(raw)
            is_new = ev["calendar_event_id"] not in self._events_cache
            self._events_cache[ev["calendar_event_id"]] = ev
            return SyncResult(connector=self.name, items_synced=1, items_created=1 if is_new else 0, items_updated=0 if is_new else 1)
        if "deleted" in etype:
            self._events_cache.pop(raw.get("event_id", ""), None)
            return SyncResult(connector=self.name, items_synced=1)
        return None

    def parse_event(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        try:
            start = datetime.fromisoformat(raw.get("start_time", ""))
        except (ValueError, TypeError):
            start = datetime.now()
        try:
            end = datetime.fromisoformat(raw.get("end_time", ""))
        except (ValueError, TypeError):
            end = datetime.now()
        return {"calendar_event_id": raw.get("event_id", ""), "title": raw.get("summary", ""), "start": start, "end": end}

    def get_cached_events(self) -> List[Dict[str, Any]]:
        return list(self._events_cache.values())
