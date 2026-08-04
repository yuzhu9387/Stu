import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.event import Event
from app.models.task import Task
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator


class _ScriptedRouter:
    """Returns canned JSON for think and canned text for react."""
    def __init__(self, think_payload, react_text):
        self._think = think_payload
        self._react = react_text
        self.react_task_types = []

    async def complete_json(self, task_type, messages, **kw):
        return self._think

    async def complete(self, task_type, messages, **kw):
        self.react_task_types.append(task_type)
        return self._react


async def test_orchestrator_create_task_flow(session):
    user = User(name="Yuzhu", lark_user_id="orch_u1", preferences={})
    session.add(user)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={
            "intent": "add task",
            "actions": [{"type": "create_task", "params": {"title": "buy milk"}}],
            "should_reply": True,
            "reply_complexity": "low",
            "reply_hint": "confirm friendly",
            "reasoning": "",
        },
        react_text="Done, added 'buy milk'.",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    out = await orch.handle(user_id=user.id, message="add task buy milk")
    assert out.reply == "Done, added 'buy milk'."
    assert out.actions_taken == ["task_created"]

    tasks = (await session.execute(select(Task))).scalars().all()
    events = (await session.execute(select(Event))).scalars().all()
    convs = (await session.execute(select(Conversation))).scalars().all()
    assert len(tasks) == 1
    assert len(events) == 1 and events[0].type == "task_created"
    roles = {c.role for c in convs}
    assert {"user", "assistant"} <= roles
    user_conv = next(c for c in convs if c.role == "user")
    assert events[0].conversation_id == user_conv.id


async def test_orchestrator_silent_turn(session):
    user = User(name="A", lark_user_id="orch_u2", preferences={})
    session.add(user)
    await session.commit()
    t = Task(user_id=user.id, title="report", status="pending")
    session.add(t)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={
            "intent": "confirm done",
            "actions": [{"type": "complete_task", "params": {"task_id": t.id}}],
            "should_reply": False,
            "reply_complexity": "low",
            "reply_hint": None,
            "reasoning": "",
        },
        react_text="(not used)",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    out = await orch.handle(user_id=user.id, message="ok")
    assert out.reply is None
    assert out.actions_taken == ["task_completed"]
    await session.refresh(t)
    assert t.status == "done"


async def test_orchestrator_high_complexity_uses_reasoning_model(session):
    user = User(name="A", lark_user_id="orch_u3", preferences={})
    session.add(user)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={
            "intent": "analysis",
            "actions": [],
            "should_reply": True,
            "reply_complexity": "high",
            "reply_hint": "give thorough analysis",
            "reasoning": "",
        },
        react_text="Detailed analysis...",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    await orch.handle(user_id=user.id, message="how am I doing this week?")
    assert router.react_task_types == ["reasoning"]


async def test_orchestrator_schedules_embed_for_user_message(session, monkeypatch):
    """Smoke: orchestrator triggers a background embed call for the user message."""
    user = User(name="X", lark_user_id="orch_emb_smoke", preferences={})
    session.add(user)
    await session.commit()

    embed_calls = []
    async def fake_embed(s, uid, source_type, source_id, content):
        embed_calls.append({"source_type": source_type, "content": content})
    monkeypatch.setattr("app.orchestrator.conversation.embed_and_store", fake_embed)

    router = _ScriptedRouter(
        think_payload={"intent": "noop", "actions": [], "should_reply": False,
                       "reply_complexity": "low", "reply_hint": None, "reasoning": ""},
        react_text="(unused)",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    await orch.handle(user_id=user.id, message="hello there")

    import asyncio as _asyncio
    await _asyncio.sleep(0.05)
    assert any(c["source_type"] == "conversation" and "hello there" in c["content"]
               for c in embed_calls)


async def test_orchestrator_passes_message_as_query_text(session, monkeypatch):
    captured = {}
    async def fake_load_context(user_id, session_, query_text=""):
        captured["query_text"] = query_text
        from app.orchestrator.context import Context
        from app.schemas.preferences import Profile
        return Context(
            user_id=user_id, user_name="T", profile=Profile(),
            procedural_patterns=[], onboarding_status="pending",
            active_flow=None, flow_filled_fields={}, flow_missing_fields=[],
            recent_turns=[], open_tasks=[],
            active_goals=[], active_habits=[],
            episodic_recall=[],
        )
    monkeypatch.setattr("app.orchestrator.conversation.load_context", fake_load_context)

    user = User(name="A", lark_user_id="qt_u1", preferences={})
    session.add(user)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={"intent": "noop", "actions": [], "should_reply": False,
                       "reply_complexity": "low", "reply_hint": None, "reasoning": ""},
        react_text="(unused)",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    await orch.handle(user_id=user.id, message="how am I doing this week?")
    assert captured["query_text"] == "how am I doing this week?"
