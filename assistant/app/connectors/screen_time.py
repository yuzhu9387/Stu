from __future__ import annotations
from datetime import date
from typing import Optional, Dict, Any, List
from app.connectors.base import BaseConnector, SyncResult


class ScreenTimeConnector(BaseConnector):
    def __init__(self):
        self._data: Dict[int, Dict[date, List[Dict[str, Any]]]] = {}

    @property
    def name(self) -> str:
        return "screen_time"

    async def sync(self, user_id: int) -> SyncResult:
        return SyncResult(connector=self.name, items_synced=0)

    async def on_event(self, event_data: Dict[str, Any]) -> Optional[SyncResult]:
        user_id = event_data.get("user_id", 0)
        date_str = event_data.get("date", "")
        entries = event_data.get("entries", [])
        try:
            day = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return SyncResult(connector=self.name, errors=["Invalid date"])
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id][day] = entries
        return SyncResult(connector=self.name, items_synced=len(entries))

    def get_daily_summary(self, user_id: int, day: date) -> Dict[str, Any]:
        entries = self._data.get(user_id, {}).get(day, [])
        total = sum(e.get("minutes", 0) for e in entries)
        by_cat: Dict[str, int] = {}
        by_app: Dict[str, int] = {}
        for e in entries:
            by_cat[e.get("category", "other")] = by_cat.get(e.get("category", "other"), 0) + e.get("minutes", 0)
            by_app[e.get("app", "unknown")] = by_app.get(e.get("app", "unknown"), 0) + e.get("minutes", 0)
        return {"total_minutes": total, "by_category": by_cat, "by_app": by_app}
