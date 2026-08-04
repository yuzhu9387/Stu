from datetime import datetime
from app.schemas.preferences import Profile, Pattern, UserPreferences


def test_profile_optional_fields():
    p = Profile()
    assert p.name is None
    assert p.wake_up is None


def test_user_preferences_round_trip():
    raw = {
        "profile": {"name": "Yuzhu", "wake_up": "07:00"},
        "procedural": [
            {"pattern": "no 7am pings", "confidence": 0.8, "learned_at": "2026-05-20T10:00:00"}
        ],
        "onboarding_status": "in_progress",
    }
    prefs = UserPreferences.model_validate(raw)
    assert prefs.profile.name == "Yuzhu"
    assert prefs.procedural[0].pattern == "no 7am pings"
    assert prefs.onboarding_status == "in_progress"
    dumped = prefs.model_dump()
    again = UserPreferences.model_validate(dumped)
    assert again.profile.name == "Yuzhu"


def test_user_preferences_empty_default():
    prefs = UserPreferences()
    assert prefs.profile.name is None
    assert prefs.procedural == []
    assert prefs.onboarding_status == "pending"


def test_pattern_has_last_reinforced_at_field():
    p = Pattern(pattern="x", confidence=0.5, learned_at="2026-05-26T00:00:00",
                last_reinforced_at="2026-05-26T12:00:00")
    assert p.last_reinforced_at == "2026-05-26T12:00:00"


def test_pattern_last_reinforced_at_defaults_to_none():
    p = Pattern(pattern="x")
    assert p.last_reinforced_at is None


def test_user_preferences_pattern_round_trip_with_last_reinforced_at():
    raw = {
        "profile": {},
        "procedural": [
            {"pattern": "test", "confidence": 0.7, "learned_at": "2026-05-26T00:00:00",
             "last_reinforced_at": "2026-05-26T08:00:00"},
        ],
    }
    prefs = UserPreferences.model_validate(raw)
    assert prefs.procedural[0].last_reinforced_at == "2026-05-26T08:00:00"
    again = UserPreferences.model_validate(prefs.model_dump())
    assert again.procedural[0].last_reinforced_at == "2026-05-26T08:00:00"
