from app.persona import PERSONA_REACT, load_persona


def test_persona_has_core_traits():
    text = PERSONA_REACT.lower()
    for trait in ["altruistic", "reliable", "boundar", "concise"]:
        assert trait in text


def test_load_persona_substitutes_name():
    rendered = load_persona("Alice")
    assert "Alice" in rendered
    assert "{user_name}" not in rendered


def test_load_persona_default_name():
    rendered = load_persona()
    assert "{user_name}" not in rendered
