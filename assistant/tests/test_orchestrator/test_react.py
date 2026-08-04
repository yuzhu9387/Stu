from app.orchestrator.context import Context
from app.orchestrator.react import react
from app.schemas.preferences import Profile


class _FakeRouter:
    def __init__(self, output: str):
        self._output = output
        self.calls = []

    async def complete(self, task_type, messages, **kw):
        self.calls.append({"task_type": task_type, "messages": messages, "kwargs": kw})
        return self._output


def _ctx(name="Test"):
    return Context(
        user_id=1, user_name=name,
        profile=Profile(), procedural_patterns=[],
        onboarding_status="pending", active_flow=None,
        flow_filled_fields={}, flow_missing_fields=[],
        recent_turns=[], open_tasks=[],
        active_goals=[], active_habits=[],
        episodic_recall=[],
    )


async def test_react_returns_text():
    router = _FakeRouter("Got it, added it to your list.")
    out = await react(_ctx(), "add task X", action_results=[], hint=None, complexity="low", llm=router)
    assert "added" in out.lower()
    assert router.calls[0]["task_type"] == "react"


async def test_react_uses_reasoning_when_complexity_high():
    router = _FakeRouter("Here's a detailed analysis...")
    await react(_ctx(), "summarize my week", action_results=[], hint=None, complexity="high", llm=router)
    assert router.calls[0]["task_type"] == "reasoning"


async def test_react_includes_persona_user_name():
    router = _FakeRouter("ok")
    await react(_ctx(name="Alice"), "hi", action_results=[], hint=None, complexity="low", llm=router)
    sys_msg = router.calls[0]["messages"][0]["content"]
    assert "Alice" in sys_msg


async def test_react_includes_action_results_in_user_message():
    router = _FakeRouter("ok")
    await react(
        _ctx(), "add task X",
        action_results=[{"type": "create_task", "entity_id": 42}],
        hint="be brief",
        complexity="low",
        llm=router,
    )
    user_msg = router.calls[0]["messages"][1]["content"]
    assert "create_task" in user_msg
    assert "be brief" in user_msg


async def test_react_uses_trigger_payload_in_user_content():
    router = _FakeRouter("ok")
    from app.orchestrator.triggers import MorningBriefTrigger
    await react(
        _ctx(),
        message="[SYSTEM_TRIGGER:morning_brief] ...",
        action_results=[],
        hint=None,
        complexity="low",
        llm=router,
    )
    user_msg = router.calls[0]["messages"][1]["content"]
    assert "SYSTEM_TRIGGER:morning_brief" in user_msg


async def test_react_evening_recap_uses_reasoning_model():
    router = _FakeRouter("recap text")
    await react(
        _ctx(),
        message="[SYSTEM_TRIGGER:evening_recap] ...",
        action_results=[],
        hint="four paragraphs",
        complexity="high",
        llm=router,
    )
    assert router.calls[0]["task_type"] == "reasoning"


async def test_react_uses_coach_persona_when_active_flow_coach():
    router = _FakeRouter("a coach reply")
    ctx = _ctx()
    ctx.active_flow = "coach"
    from app.orchestrator.react import react
    await react(ctx, "I'm stuck", action_results=[], hint=None, complexity="low", llm=router)
    sys_msg = router.calls[0]["messages"][0]["content"]
    assert "COACH MODE" in sys_msg or "coach mode" in sys_msg.lower()
    # Coach prompts/react.md content also present
    assert "Socratic" in sys_msg or "first principles" in sys_msg.lower()


async def test_react_passes_web_search_tool_in_coach_mode():
    router = _FakeRouter("ok")
    ctx = _ctx()
    ctx.active_flow = "coach"
    from app.orchestrator.react import react
    await react(ctx, "I'm stuck", action_results=[], hint=None, complexity="low", llm=router)
    call_kwargs = router.calls[0].get("kwargs", {})
    tools = call_kwargs.get("tools")
    assert tools is not None
    assert len(tools) == 1
    assert tools[0]["name"] == "web_search"


async def test_react_forces_reasoning_model_in_coach_mode():
    router = _FakeRouter("ok")
    ctx = _ctx()
    ctx.active_flow = "coach"
    from app.orchestrator.react import react
    await react(ctx, "I'm stuck", action_results=[], hint=None, complexity="low", llm=router)
    # Even though complexity="low", coach mode forces reasoning
    assert router.calls[0]["task_type"] == "reasoning"


async def test_react_normal_mode_no_tools():
    router = _FakeRouter("ok")
    ctx = _ctx()  # active_flow is None or non-coach
    from app.orchestrator.react import react
    await react(ctx, "hi", action_results=[], hint=None, complexity="low", llm=router)
    call_kwargs = router.calls[0].get("kwargs", {})
    assert call_kwargs.get("tools") is None
