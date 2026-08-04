import pytest
from datetime import date
from app.services.reports import ReportService
from app.models.user import User
from app.models.task import Task


@pytest.mark.asyncio
async def test_generate_daily(session):
    user = User(name="T", lark_user_id="lark_rpt1")
    session.add(user)
    await session.commit()
    session.add_all([Task(user_id=user.id, title="A", status="completed"), Task(user_id=user.id, title="B", status="pending")])
    await session.commit()
    report = await ReportService(session).generate_daily(user.id, date(2026, 5, 12))
    assert report.report_type == "daily" and "completion_rate" in report.data

@pytest.mark.asyncio
async def test_generate_weekly(session):
    user = User(name="T", lark_user_id="lark_rpt2")
    session.add(user)
    await session.commit()
    report = await ReportService(session).generate_weekly(user.id, date(2026, 5, 12))
    assert report.report_type == "weekly"

@pytest.mark.asyncio
async def test_list_reports(session):
    user = User(name="T", lark_user_id="lark_rpt3")
    session.add(user)
    await session.commit()
    svc = ReportService(session)
    await svc.generate_daily(user.id, date(2026, 5, 12))
    await svc.generate_daily(user.id, date(2026, 5, 13))
    reports = await svc.list_by_user(user.id, report_type="daily")
    assert len(reports) == 2
