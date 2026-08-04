from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class SyncResult:
    connector: str
    items_synced: int = 0
    items_created: int = 0
    items_updated: int = 0
    errors: List[str] = field(default_factory=list)
    synced_at: Optional[datetime] = None


class BaseConnector(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def sync(self, user_id: int) -> SyncResult: ...

    @abstractmethod
    async def on_event(self, event_data: Dict[str, Any]) -> Optional[SyncResult]: ...
