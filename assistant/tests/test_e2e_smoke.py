from sqlalchemy import select

from app.models.event import Event
from app.models.task import Task
from app.models.user import User


class _ScriptedRouter:
    def __init__(self, script: list[dict], react_text: str = "ok"):
        self._script = list(script)
        self._react_text = react_text

    async def complete_json(self, task_type, messages, **kw):
        return self._script.pop(0)

    async def complete(self, task_type, messages, **kw):
        return self._react_text


async def test_full_happy_path(client, monkeypatch, session):
    script = [
        # Turn 1: start onboarding
        {
            "intent": "start onboarding",
            "actions": [{"type": "start_flow", "params": {"flow_name": "onboarding"}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "ask first question", "reasoning": "",
        },
        # Turn 2: answer wake_up
        {
            "intent": "answer wake_up",
            "actions": [{"type": "update_profile", "params": {"path": "wake_up", "value": "07:00"}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "ask next field", "reasoning": "",
        },
        # Turn 3: add a task
        {
            "intent": "add task",
            "actions": [{"type": "create_task", "params": {"title": "weekly report"}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "", "reasoning": "",
        },
        # Turn 4: complete the task (task_id patched after creation)
        {
            "intent": "complete task",
            "actions": [{"type": "complete_task", "params": {"task_id": None}}],
            "should_reply": False, "reply_complexity": "low",
            "reply_hint": None, "reasoning": "",
        },
    ]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, task_type, messages, **kw): return script.pop(0)
        async def complete(self, task_type, messages, **kw): return "ok"

    monkeypatch.setattr("app.routers.conversation.LLMRouter", _Router)

    user_resp = await client.post("/api/users", json={"name": "Yuzhu", "lark_user_id": "e2e_u1"})
    user_id = user_resp.json()["id"]

    # Turn 1
    r1 = await client.post("/api/conversation", json={"user_id": user_id, "message": "start"})
    assert r1.status_code == 200 and r1.json()["actions_taken"] == ["flow_started"]

    # Turn 2
    r2 = await client.post("/api/conversation", json={"user_id": user_id, "message": "I wake up at 7"})
    assert r2.json()["actions_taken"] == ["profile_updated"]

    # Turn 3
    r3 = await client.post("/api/conversation", json={"user_id": user_id, "message": "add task weekly report"})
    assert r3.json()["actions_taken"] == ["task_created"]

    # Look up created task id, patch the script
    task = (await session.execute(select(Task).where(Task.user_id == user_id))).scalar_one()
    script[0]["actions"][0]["params"]["task_id"] = task.id

    # Turn 4
    r4 = await client.post("/api/conversation", json={"user_id": user_id, "message": "done"})
    assert r4.json()["actions_taken"] == ["task_completed"]
    assert r4.json()["reply"] is None

    # Verify event log
    events = (await session.execute(select(Event).where(Event.user_id == user_id).order_by(Event.id))).scalars().all()
    event_types = [e.type for e in events]
    assert event_types == [
        "flow_started",
        "profile_updated",
        "task_created",
        "task_completed",
    ]
