import pytest


async def test_conversation_endpoint_create_task(client, monkeypatch):
    class _StubRouter:
        def __init__(self, **_):
            pass
        async def complete_json(self, task_type, messages, **kw):
            return {
                "intent": "add task",
                "actions": [{"type": "create_task", "params": {"title": "buy milk"}}],
                "should_reply": True,
                "reply_complexity": "low",
                "reply_hint": "confirm",
                "reasoning": "",
            }
        async def complete(self, task_type, messages, **kw):
            return "Got it."
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _StubRouter)

    user_resp = await client.post("/api/users", json={"name": "U", "lark_user_id": "conv_u1"})
    user_id = user_resp.json()["id"]
    resp = await client.post("/api/conversation", json={"user_id": user_id, "message": "add task buy milk"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Got it."
    assert data["actions_taken"] == ["task_created"]


async def test_conversation_endpoint_silent_turn(client, monkeypatch):
    class _StubRouter:
        def __init__(self, **_):
            pass
        async def complete_json(self, task_type, messages, **kw):
            return {
                "intent": "noop",
                "actions": [],
                "should_reply": False,
                "reply_complexity": "low",
                "reply_hint": None,
                "reasoning": "",
            }
        async def complete(self, task_type, messages, **kw):
            raise AssertionError("should not be called")
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _StubRouter)

    user_resp = await client.post("/api/users", json={"name": "U", "lark_user_id": "conv_u2"})
    user_id = user_resp.json()["id"]
    resp = await client.post("/api/conversation", json={"user_id": user_id, "message": "ok"})
    assert resp.status_code == 200
    assert resp.json()["reply"] is None


async def test_conversation_endpoint_unknown_user_404(client):
    resp = await client.post("/api/conversation", json={"user_id": 99999, "message": "hi"})
    assert resp.status_code == 404
