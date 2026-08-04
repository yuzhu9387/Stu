from datetime import date
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel
from app.connectors.screen_time import ScreenTimeConnector

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])
_screen_time = ScreenTimeConnector()


class ScreenTimeEntry(BaseModel):
    app: str
    minutes: int
    category: str = "other"

class ScreenTimeUpload(BaseModel):
    date: str
    entries: List[ScreenTimeEntry]


@router.post("/screen-time/{user_id}")
async def upload_screen_time(user_id: int, data: ScreenTimeUpload):
    result = await _screen_time.on_event({"user_id": user_id, "date": data.date, "entries": [e.model_dump() for e in data.entries]})
    return {"items_synced": result.items_synced if result else 0}

@router.get("/screen-time/{user_id}/{day}")
async def get_screen_time(user_id: int, day: date):
    return _screen_time.get_daily_summary(user_id, day)
