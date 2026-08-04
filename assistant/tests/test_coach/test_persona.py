from app.coach.persona import COACH_PERSONA, load_coach_persona


def test_persona_has_required_concepts():
    text = COACH_PERSONA.lower()
    for keyword in ["socratic", "first principles", "third-party", "ask", "don't tell"]:
        assert keyword in text, f"missing keyword: {keyword}"


def test_persona_substitutes_user_name():
    rendered = load_coach_persona("Alice")
    assert "Alice" in rendered
    assert "{user_name}" not in rendered


def test_load_coach_persona_default():
    rendered = load_coach_persona()
    assert "{user_name}" not in rendered


def test_persona_forbids_data_mutating():
    text = COACH_PERSONA.lower()
    assert "create tasks" in text or "modify goals" in text
