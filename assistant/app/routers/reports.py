from typing import Optional, List, Dict, Any
from datetime import date
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session
from app.services.reports import ReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])


class DailyReq(BaseModel):
    date: str

class WeeklyReq(BaseModel):
    week_end: str

class ReportRead(BaseModel):
    id: int
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    data: Optional[Dict[str, Any]]
    ai_insights: Optional[str]
    model_config = {"from_attributes": True}


@router.post("/{user_id}/daily", status_code=201, response_model=ReportRead)
async def gen_daily(user_id: int, req: DailyReq, session: AsyncSession = Depends(get_session)):
    return await ReportService(session).generate_daily(user_id, date.fromisoformat(req.date))

@router.post("/{user_id}/weekly", status_code=201, response_model=ReportRead)
async def gen_weekly(user_id: int, req: WeeklyReq, session: AsyncSession = Depends(get_session)):
    return await ReportService(session).generate_weekly(user_id, date.fromisoformat(req.week_end))

@router.get("/{user_id}", response_model=List[ReportRead])
async def list_reports(user_id: int, report_type: Optional[str] = None, session: AsyncSession = Depends(get_session)):
    return await ReportService(session).list_by_user(user_id, report_type)
