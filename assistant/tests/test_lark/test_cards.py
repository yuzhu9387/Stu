from app.lark.cards import CardBuilder


def test_question_card():
    card = CardBuilder.question_card(title="Onboarding", question="What time do you wake up?")
    assert card["header"]["title"]["content"] == "Onboarding"
    assert any("wake up" in str(e) for e in card["elements"])


def test_question_card_with_options():
    card = CardBuilder.question_card(title="Preferences", question="How often?", options=["daily", "weekly", "never"])
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions) == 1
    assert len(actions[0]["actions"]) == 3


def test_confirm_card():
    card = CardBuilder.confirm_card(title="Task Created", summary="Write report\nDeadline: 2026-05-15")
    assert card["header"]["title"]["content"] == "Task Created"
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions[0]["actions"]) == 2


def test_plan_card():
    slots = [{"time": "09:00-09:30", "content": "Reply emails", "type": "task"}, {"time": "09:30-10:00", "content": "Stand-up", "type": "calendar_event"}]
    card = CardBuilder.plan_card(title="Today's Plan", slots=slots)
    assert any("Reply emails" in str(e) for e in card["elements"])


def test_reminder_card():
    card = CardBuilder.reminder_card(task_title="Write report", message="Time to start (3h)")
    assert any("Write report" in str(e) for e in card["elements"])


def test_summary_card():
    card = CardBuilder.summary_card(title="Daily Summary", stats={"completed": 8, "total": 10, "completion_rate": "80%"}, dashboard_url="https://example.com")
    assert any("80%" in str(e) for e in card["elements"])
