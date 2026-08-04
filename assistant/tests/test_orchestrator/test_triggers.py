import pytest
from pydantic import ValidationError
from app.orchestrator.triggers import (
    WelcomeTrigger,
    TaskCheckinTrigger,
    MorningBriefTrigger,
    EveningRecapTrigger,
    synthetic_message_for,
)


def test_welcome_trigger_default_fields():
    t = WelcomeTrigger()
    assert t.type == "welcome"
    assert t.initial_message is None


def test_welcome_trigger_with_initial():
    t = WelcomeTrigger(initial_message="hi")
    assert t.initial_message == "hi"


def test_task_checkin_required_fields():
    with pytest.raises(ValidationError):
        TaskCheckinTrigger()


def test_task_checkin_full():
    t = TaskCheckinTrigger(
        task_id=1, attempt=1, task_title="write report", deadline="2026-05-21T14:00:00Z"
    )
    assert t.type == "task_checkin"
    assert t.attempt == 1


def test_morning_brief_lists_default_empty():
    t = MorningBriefTrigger(date="2026-05-21")
    assert t.today_plan == []
    assert t.habits_today == []
    assert t.headline_task is None


def test_evening_recap_payload():
    t = EveningRecapTrigger(
        date="2026-05-21",
        tasks_completed=[{"id": 1, "title": "x"}],
        recent_pattern={"avg_completion_rate": 0.7},
    )
    assert t.tasks_completed[0]["id"] == 1


def test_synthetic_message_welcome():
    s = synthetic_message_for(WelcomeTrigger(initial_message="hello"))
    assert "welcome" in s.lower() or "new user" in s.lower()
    assert "hello" in s


def test_synthetic_message_task_checkin():
    t = TaskCheckinTrigger(task_id=42, attempt=2, task_title="email replies", deadline="2026-05-21T10:00:00Z")
    s = synthetic_message_for(t)
    assert "email replies" in s
    assert "attempt 2" in s.lower() or "2nd" in s.lower() or "second" in s.lower()


def test_synthetic_message_morning_brief():
    t = MorningBriefTrigger(date="2026-05-21", headline_task="quarterly review")
    s = synthetic_message_for(t)
    assert "morning" in s.lower()
    assert "quarterly review" in s


def test_synthetic_message_evening_recap():
    t = EveningRecapTrigger(date="2026-05-21")
    s = synthetic_message_for(t)
    assert "evening" in s.lower() or "recap" in s.lower()


def test_coach_opening_trigger_requires_reason():
    from app.orchestrator.triggers import CoachOpeningTrigger
    with pytest.raises(ValidationError):
        CoachOpeningTrigger()


def test_coach_opening_trigger_carries_reason():
    from app.orchestrator.triggers import CoachOpeningTrigger
    t = CoachOpeningTrigger(reason="3-day silence")
    assert t.type == "coach_opening"
    assert t.reason == "3-day silence"


def test_synthetic_message_coach_opening_includes_reason():
    from app.orchestrator.triggers import CoachOpeningTrigger
    t = CoachOpeningTrigger(reason="task 'X' pushed 3 times")
    s = synthetic_message_for(t)
    assert "coach_opening" in s.lower() or "coach" in s.lower()
    assert "task 'X' pushed 3 times" in s
