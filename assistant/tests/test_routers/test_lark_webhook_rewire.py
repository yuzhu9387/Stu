import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.user import User


def _msg_payload(open_id: str, text: str):
    return {
        "schema": "2.0",
        "header": {
            "event_id": f"evt_{open_id}_{text[:8]}",
            "event_type": "im.message.receive_v1",
            "token": "test-verify-token",
        },
        "event": {
            "sender": {"sender_id": {"open_id": open_id}},
            "message": {
                "message_id": f"mid_{open_id}",
                "message_type": "text",
                "content": '{"text":"' + text + '"}',
            },
        },
    }


async def test_webhook_new_user_creates_user_and_triggers_welcome(client, session, monkeypatch):
    class _StubRouter:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            raise AssertionError("THINK should not run on welcome path")
        async def complete(self, task_type, messages, **kw):
            return "Hi! What time do you usually wake up?"
    monkeypatch.setattr("app.routers.lark_webhook.LLMRouter", _StubRouter)
    monkeypatch.setattr("app.routers.lark_webhook.settings.proactive_dry_run", True)

    payload = _msg_payload("open_xxx_new", "hello")
    resp = await client.post("/api/lark/webhook", json=payload)
    assert resp.status_code == 200

    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1 and users[0].lark_user_id == "open_xxx_new"
    flows = (await session.execute(select(DialogueSession))).scalars().all()
    assert len(flows) == 1 and flows[0].flow_type == "onboarding"
    events = (await session.execute(select(Event))).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert "welcome_sent" in types
    convs = (await session.execute(select(Conversation))).scalars().all()
    assert any(c.role == "assistant" and c.intent == "proactive:welcome" for c in convs)


async def test_webhook_existing_user_routes_to_handle(client, session, monkeypatch):
    user = User(name="E", lark_user_id="open_existing", preferences={})
    session.add(user)
    await session.commit()

    class _StubRouter:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return {
                "intent": "greeting",
                "actions": [],
                "should_reply": True,
                "reply_complexity": "low",
                "reply_hint": "say hi back",
                "reasoning": "",
            }
        async def complete(self, *a, **kw):
            return "Hey!"
    monkeypatch.setattr("app.routers.lark_webhook.LLMRouter", _StubRouter)
    monkeypatch.setattr("app.routers.lark_webhook.settings.proactive_dry_run", True)

    payload = _msg_payload("open_existing", "hi")
    resp = await client.post("/api/lark/webhook", json=payload)
    assert resp.status_code == 200

    convs = (await session.execute(select(Conversation))).scalars().all()
    roles = {c.role for c in convs}
    assert {"user", "assistant"} <= roles


async def test_webhook_url_verification_passes_through(client):
    resp = await client.post("/api/lark/webhook", json={
        "type": "url_verification", "token": "test-verify-token", "challenge": "abc"
    })
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc"}


async def test_webhook_invalid_token_returns_403(client):
    resp = await client.post("/api/lark/webhook", json={
        "type": "url_verification", "token": "WRONG", "challenge": "abc"
    })
    assert resp.status_code == 403
