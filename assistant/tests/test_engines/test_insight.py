import pytest
from datetime import date, time
from app.engines.insight import InsightEngine, DailyStats


def test_daily_stats():
    slots = [{"start": time(9,0), "end": time(10,0), "type": "task"}, {"start": time(10,0), "end": time(10,30), "type": "calendar_event"}, {"start": time(10,30), "end": time(11,0), "type": "task"}]
    stats = InsightEngine().compute_daily(date=date(2026,5,12), planned_slots=slots, completed_task_ids=[1,3], total_task_ids=[1,2,3])
    assert stats.completion_rate == pytest.approx(2/3, rel=0.01)
    assert stats.total_planned_minutes == 120
    assert stats.meeting_minutes == 30


def test_time_distribution():
    slots = [{"start": time(9,0), "end": time(10,0), "type": "task"}, {"start": time(10,0), "end": time(11,0), "type": "calendar_event"}]
    stats = InsightEngine().compute_daily(date=date(2026,5,12), planned_slots=slots, completed_task_ids=[], total_task_ids=[])
    assert stats.time_distribution["task"] == 60
    assert stats.time_distribution["calendar_event"] == 60


def test_weekly_stats():
    daily = [
        DailyStats(date=date(2026,5,11), completion_rate=0.8, total_planned_minutes=480, meeting_minutes=60, screen_time_minutes=300, time_distribution={"task": 300}),
        DailyStats(date=date(2026,5,12), completion_rate=0.9, total_planned_minutes=480, meeting_minutes=90, screen_time_minutes=280, time_distribution={"task": 280}),
    ]
    weekly = InsightEngine().compute_weekly(daily, {"Workout": (2, 3)})
    assert weekly.avg_completion_rate == pytest.approx(0.85, rel=0.01)
    assert weekly.total_meeting_minutes == 150
    assert weekly.habit_adherence["Workout"] == pytest.approx(2/3, rel=0.01)


def test_goal_progress():
    goals = [{"title": "Read 12 books", "target": 12, "current": 5}, {"title": "Earn 5M", "target": 5000000, "current": 2100000}]
    progress = InsightEngine().compute_goal_progress(goals)
    assert progress[0]["progress"] == pytest.approx(5/12, rel=0.01)
    assert progress[1]["progress"] == pytest.approx(0.42, rel=0.01)
