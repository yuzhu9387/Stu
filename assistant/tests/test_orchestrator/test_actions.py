import pytest
from pydantic import ValidationError
from app.orchestrator.actions import (
    ActionType,
    CreateTaskParams,
    UpdateProfileParams,
    RecordPatternParams,
    parse_action,
)


def test_create_task_params_required_title():
    with pytest.raises(ValidationError):
        CreateTaskParams()


def test_create_task_params_accepts_optional_fields():
    p = CreateTaskParams(title="x", deadline="2026-05-21", estimated_minutes=30)
    assert p.title == "x"


def test_update_profile_params():
    p = UpdateProfileParams(path="diet", value="vegetarian")
    assert p.path == "diet"


def test_record_pattern_params():
    p = RecordPatternParams(pattern="user dislikes 7am pings", confidence=0.8)
    assert p.confidence == 0.8


def test_parse_action_dispatch():
    raw = {"type": "create_task", "params": {"title": "x"}}
    parsed = parse_action(raw)
    assert parsed.type == ActionType.CREATE_TASK
    assert parsed.params.title == "x"


def test_parse_action_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_action({"type": "fly_to_mars", "params": {}})


from app.orchestrator.actions import (
    ReinforcePatternParams, ContradictPatternParams,
)


def test_reinforce_pattern_action_type_exists():
    assert ActionType.REINFORCE_PATTERN.value == "reinforce_pattern"


def test_contradict_pattern_action_type_exists():
    assert ActionType.CONTRADICT_PATTERN.value == "contradict_pattern"


def test_reinforce_pattern_params_defaults():
    p = ReinforcePatternParams(pattern_substring="early reminders")
    assert p.delta == 0.1


def test_contradict_pattern_params_defaults():
    p = ContradictPatternParams(pattern_substring="early reminders")
    assert p.delta == 0.3


def test_parse_action_reinforce_pattern():
    parsed = parse_action({"type": "reinforce_pattern",
                           "params": {"pattern_substring": "diet", "delta": 0.2}})
    assert parsed.type == ActionType.REINFORCE_PATTERN
    assert parsed.params.delta == 0.2


from app.orchestrator.actions import EndCoachSessionParams


def test_end_coach_session_action_type_exists():
    assert ActionType.END_COACH_SESSION.value == "end_coach_session"


def test_end_coach_session_params_no_required_fields():
    p = EndCoachSessionParams()
    assert p is not None


def test_parse_action_end_coach_session():
    parsed = parse_action({"type": "end_coach_session", "params": {}})
    assert parsed.type == ActionType.END_COACH_SESSION
    assert isinstance(parsed.params, EndCoachSessionParams)
