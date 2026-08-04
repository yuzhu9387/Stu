import pytest
from sqlalchemy import select

from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.user import User


async def test_coach_session_full_loop(client, session, monkeypatch):
    """E2E: user invokes coach, has a multi-turn reflection, then ends the session."""

    user = User(name="X", lark_user_id="coach_e2e_u1", preferences={})
    session.add(user)
    await session.commit()

    think_script = [
        # Turn 1: user invokes coach
        {
            "intent": "user wants reflective dialogue about Q2 report",
            "actions": [{
                "type": "start_flow",
                "params": {"flow_name": "coach"},
            }],
            "should_reply": True, "reply_complexity": "high",
            "reply_hint": "open with one question", "reasoning": "",
        },
        # Turn 2: user replies (in coach mode now)
        {
            "intent": "user reflects",
            "actions": [],  # coach mode → no data mutations
            "should_reply": True, "reply_complexity": "high",
            "reply_hint": "ask one deeper question", "reasoning": "",
        },
        # Turn 3: user signals done
        {
            "intent": "user wants to end coach session",
            "actions": [{"type": "end_coach_session", "params": {}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "warm closing", "reasoning": "",
        },
    ]
    react_script = [
        "Q2 报告这事儿挺重的——你觉得你真正卡在哪儿？",
        "嗯，那如果时间不是问题，你最担心的还是什么？",
        "好的，慢慢消化，需要再聊随时找我。",
    ]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return think_script.pop(0)
        async def complete(self, task_type, messages, **kw):
            return react_script.pop(0)
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _Router)

    # Turn 1: invoke coach
    r1 = await client.post("/api/conversation",
                           json={"user_id": user.id, "message": "咱们聊聊 Q2 报告"})
    assert r1.status_code == 200
    flows = (await session.execute(
        select(DialogueSession).where(DialogueSession.user_id == user.id)
    )).scalars().all()
    assert len(flows) == 1
    assert flows[0].flow_type == "coach"
    assert flows[0].status == "active"

    # Turn 2: reflect
    r2 = await client.post("/api/conversation",
                           json={"user_id": user.id, "message": "我也不知道，就是不想开始"})
    assert r2.status_code == 200

    # Turn 3: end
    r3 = await client.post("/api/conversation",
                           json={"user_id": user.id, "message": "好，先这样，谢谢"})
    assert r3.status_code == 200

    await session.refresh(flows[0])
    assert flows[0].status == "completed"

    # Verify the events trail
    events = (await session.execute(
        select(Event).where(Event.user_id == user.id).order_by(Event.id)
    )).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert types.count("flow_completed") >= 1  # end_coach_session emits flow_completed
