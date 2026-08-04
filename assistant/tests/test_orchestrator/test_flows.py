from app.orchestrator.flows import FieldDef, FlowDefinition, ONBOARDING, get_flow


def test_onboarding_has_expected_fields():
    names = {f.name for f in ONBOARDING.required_fields}
    assert "wake_up" in names
    assert "yearly_goals" in names
    assert "daily_habits" in names


def test_field_def_carries_description():
    f = FieldDef("wake_up", type="time", description="wake-up time")
    assert f.description == "wake-up time"


def test_get_flow_by_name():
    assert get_flow("onboarding") is ONBOARDING
    assert get_flow("nope") is None


def test_missing_fields_helper():
    filled = {"wake_up": "07:00", "work_start": "09:00"}
    missing = ONBOARDING.missing_fields(filled)
    names = {f.name for f in missing}
    assert "wake_up" not in names
    assert "yearly_goals" in names


def test_onboarding_includes_user_expectations():
    names = [f.name for f in ONBOARDING.required_fields]
    assert "user_expectations" in names


def test_user_expectations_is_text_type():
    field = next(f for f in ONBOARDING.required_fields if f.name == "user_expectations")
    assert field.type == "text"


def test_coach_flow_exists_and_open_ended():
    from app.orchestrator.flows import COACH
    assert COACH.name == "coach"
    assert COACH.required_fields == ()


def test_get_flow_coach():
    coach = get_flow("coach")
    assert coach is not None
    assert coach.name == "coach"


def test_coach_flow_is_complete_with_anything():
    from app.orchestrator.flows import COACH
    assert COACH.missing_fields({}) == []
    assert COACH.is_complete({}) is True
