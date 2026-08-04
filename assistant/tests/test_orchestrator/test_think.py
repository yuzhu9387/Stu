import pytest
from app.orchestrator.actions import ActionType
from app.orchestrator.context import Context
from app.orchestrator.flows import ONBOARDING
from app.orchestrator.think import ThinkResult, think
from app.schemas.preferences import Profile


class _FakeRouter:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def complete_json(self, task_type, messages, **kw):
        self.calls.append({"task_type": task_type, "messages": messages})
        return self._payload


def _empty_ctx(user_id=1, **overrides) -> Context:
    defaults = dict(
        user_id=user_id,
        user_name="Test",
        profile=Profile(),
        procedural_patterns=[],
        onboarding_status="pending",
        active_flow=None,
        flow_filled_fields={},
        flow_missing_fields=[],
        recent_turns=[],
        open_tasks=[],
        active_goals=[],
        active_habits=[],
        episodic_recall=[],
    )
    defaults.update(overrides)
    return Context(**defaults)


async def test_think_returns_structured_result():
    router = _FakeRouter({
        "intent": "user wants to add a task",
        "actions": [{"type": "create_task", "params": {"title": "buy milk"}}],
        "should_reply": True,
        "reply_complexity": "low",
        "reply_hint": "confirm in a friendly way",
        "reasoning": "explicit task request",
    })
    result = await think(_empty_ctx(), "add task buy milk", router)
    assert isinstance(result, ThinkResult)
    assert result.intent.startswith("user wants")
    assert result.actions[0].type == ActionType.CREATE_TASK
    assert result.should_reply is True
    assert result.reply_complexity == "low"


async def test_think_handles_silent_confirmation():
    router = _FakeRouter({
        "intent": "user confirms task done",
        "actions": [{"type": "complete_task", "params": {"task_id": 7}}],
        "should_reply": False,
        "reply_complexity": "low",
        "reply_hint": None,
        "reasoning": "ok response after did-you-finish",
    })
    result = await think(_empty_ctx(), "ok", router)
    assert result.should_reply is False
    assert result.actions[0].type == ActionType.COMPLETE_TASK


async def test_think_active_flow_in_messages():
    ctx = _empty_ctx(
        active_flow="onboarding",
        flow_filled_fields={"wake_up": "07:00"},
        flow_missing_fields=list(ONBOARDING.missing_fields({"wake_up": "07:00"})),
    )
    router = _FakeRouter({
        "intent": "...", "actions": [], "should_reply": True,
        "reply_complexity": "low", "reply_hint": "", "reasoning": "",
    })
    await think(ctx, "9am", router)
    msgs_str = "\n".join(m["content"] for m in router.calls[0]["messages"] if m["role"] == "user")
    assert "onboarding" in msgs_str.lower()
    assert "wake_up" in msgs_str


async def test_think_invalid_action_skipped(monkeypatch):
    router = _FakeRouter({
        "intent": "...",
        "actions": [
            {"type": "create_task", "params": {"title": "good"}},
            {"type": "fly_to_mars", "params": {}},
        ],
        "should_reply": True,
        "reply_complexity": "low",
        "reply_hint": "",
        "reasoning": "",
    })
    result = await think(_empty_ctx(), "hi", router)
    assert len(result.actions) == 1
    assert result.actions[0].type == ActionType.CREATE_TASK


async def test_think_appends_coach_addendum_when_active_flow_is_coach():
    router = _FakeRouter({
        "intent": "reflecting", "actions": [], "should_reply": True,
        "reply_complexity": "high", "reply_hint": "", "reasoning": "",
    })
    ctx = _empty_ctx(active_flow="coach")
    await think(ctx, "I'm stuck", router)
    system_msg = router.calls[0]["messages"][0]["content"]
    assert "COACH MODE ACTIVE" in system_msg
    # Default think prompt content also present (additive, not replacement)
    assert "personal assistant" in system_msg.lower() or "decision module" in system_msg.lower()


async def test_think_does_not_append_coach_addendum_in_normal_mode():
    router = _FakeRouter({
        "intent": "hi", "actions": [], "should_reply": True,
        "reply_complexity": "low", "reply_hint": "", "reasoning": "",
    })
    ctx = _empty_ctx(active_flow=None)
    await think(ctx, "hello", router)
    system_msg = router.calls[0]["messages"][0]["content"]
    assert "COACH MODE ACTIVE" not in system_msg
