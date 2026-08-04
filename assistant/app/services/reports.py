from __future__ import annotations
from datetime import date, timedelta
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.report import Report
from app.models.task import Task


class ReportService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def generate_daily(self, user_id: int, day: date) -> Report:
        result = await self._session.execute(select(Task).where(Task.user_id == user_id))
        tasks = list(result.scalars().all())
        completed = [t for t in tasks if t.status == "completed"]
        rate = len(completed) / len(tasks) if tasks else 0.0
        data = {"completion_rate": round(rate, 2), "total_tasks": len(tasks), "completed_tasks": len(completed)}
        insights = self._daily_insight(data)
        report = Report(user_id=user_id, report_type="daily", period_start=day, period_end=day, data=data, ai_insights=insights)
        self._session.add(report)
        await self._session.commit()
        await self._session.refresh(report)
        return report

    async def generate_weekly(self, user_id: int, week_end: date) -> Report:
        week_start = week_end - timedelta(days=6)
        result = await self._session.execute(select(Task).where(Task.user_id == user_id))
        tasks = list(result.scalars().all())
        completed = [t for t in tasks if t.status == "completed"]
        rate = len(completed) / len(tasks) if tasks else 0.0
        data = {"completion_rate": round(rate, 2), "total_tasks": len(tasks), "completed_tasks": len(completed), "period": f"{week_start} to {week_end}"}
        report = Report(user_id=user_id, report_type="weekly", period_start=week_start, period_end=week_end, data=data, ai_insights=f"Weekly rate: {int(rate*100)}%")
        self._session.add(report)
        await self._session.commit()
        await self._session.refresh(report)
        return report

    async def list_by_user(self, user_id: int, report_type: Optional[str] = None) -> List[Report]:
        stmt = select(Report).where(Report.user_id == user_id)
        if report_type:
            stmt = stmt.where(Report.report_type == report_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def _daily_insight(self, data: dict) -> str:
        rate = data.get("completion_rate", 0)
        c = data.get("completed_tasks", 0)
        t = data.get("total_tasks", 0)
        if rate >= 0.9:
            return f"Excellent! {c}/{t} tasks ({int(rate*100)}%)."
        if rate >= 0.7:
            return f"Good day. {c}/{t} tasks ({int(rate*100)}%)."
        return f"Completed {c}/{t} tasks ({int(rate*100)}%). Consider re-prioritizing."
