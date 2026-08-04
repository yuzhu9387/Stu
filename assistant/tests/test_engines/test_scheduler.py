from datetime import date, time
from app.engines.scheduler import SchedulerEngine, ScheduleInput, UserPreferences


def _prefs():
    return UserPreferences(wake_up=time(7,0), work_start=time(9,0), work_end=time(18,0), sleep_time=time(23,0), peak_hours=(time(9,0), time(12,0)), lunch_break=(time(12,0), time(13,0)))


def test_empty_day():
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=[], habits=[], calendar_events=[]))
    assert len(result.slots) > 0
    assert all(s.slot_type in ("free", "break") for s in result.slots)


def test_with_tasks():
    tasks = [{"id": 1, "title": "Write report", "quadrant": "urgent_important", "estimated_minutes": 60}, {"id": 2, "title": "Reply emails", "quadrant": "neither", "estimated_minutes": 30}]
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=tasks, habits=[], calendar_events=[]))
    task_slots = [s for s in result.slots if s.slot_type == "task"]
    assert len(task_slots) >= 2
    urgent = next(s for s in task_slots if s.linked_id == 1)
    other = next(s for s in task_slots if s.linked_id == 2)
    assert urgent.start_time <= other.start_time


def test_with_calendar_events():
    events = [{"id": "c1", "title": "Stand-up", "start": time(10,0), "end": time(10,30)}]
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=[], habits=[], calendar_events=events))
    cal = [s for s in result.slots if s.slot_type == "calendar_event"]
    assert len(cal) == 1 and cal[0].title == "Stand-up"


def test_with_habits():
    habits = [{"id": 1, "title": "Workout", "duration_minutes": 60, "preferred_time": time(18,0)}]
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=[], habits=habits, calendar_events=[]))
    assert any(s.slot_type == "habit" for s in result.slots)


def test_lunch_break():
    tasks = [{"id": 1, "title": "Big", "quadrant": "urgent_important", "estimated_minutes": 480}]
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=tasks, habits=[], calendar_events=[]))
    assert any(s.slot_type == "break" and s.start_time == time(12,0) for s in result.slots)


def test_priority_ordering():
    tasks = [{"id":1,"title":"Low","quadrant":"neither","estimated_minutes":30},{"id":2,"title":"High","quadrant":"urgent_important","estimated_minutes":30}]
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=tasks, habits=[], calendar_events=[]))
    task_slots = [s for s in result.slots if s.slot_type == "task"]
    assert task_slots[0].linked_id == 2


def test_no_overlap_with_meeting():
    tasks = [{"id":1,"title":"Work","quadrant":"urgent_important","estimated_minutes":120}]
    events = [{"id":"c1","title":"Meeting","start":time(10,0),"end":time(11,0)}]
    result = SchedulerEngine().generate(ScheduleInput(date=date(2026,5,12), preferences=_prefs(), tasks=tasks, habits=[], calendar_events=events))
    task_slots = [s for s in result.slots if s.slot_type == "task"]
    for ts in task_slots:
        assert not (ts.start_time >= time(10,0) and ts.start_time < time(11,0))
