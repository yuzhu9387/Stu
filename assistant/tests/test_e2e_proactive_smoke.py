import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.event import Event
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User


async def test_full_task_to_reminder_to_completion(client, session, monkeypatch):
    """Walks: new user → welcome → user creates a task with deadline →
    user replies 'done' → task done + reminder cancelled. All via webhook."""

    think_script = [
        # Turn 2: user adds a task
        {
            "intent": "add task",
            "actions": [{
                "type": "create_task",
                "params": {
                    "title": "fast task",
                    "deadline": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                },
            }],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "confirm", "reasoning": "",
        },
        # Turn 3: user replies "done" — task_id injected at test time
        {
            "intent": "confirm done",
            "actions": [{"type": "complete_task", "params": {"task_id": None}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "celebrate briefly", "reasoning": "",
        },
    ]
    react_script = ["Hi! What's your wake-up time?", "Got it.", "Nice ✊"]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return think_script.pop(0)
        async def complete(self, task_type, messages, **kw):
            return react_script.pop(0)

    monkeypatch.setattr("app.routers.lark_webhook.LLMRouter", _Router)
    monkeypatch.setattr("app.routers.lark_webhook.settings.proactive_dry_run", True)

    # Step 1: new user → welcome
    payload_new = {
        "schema": "2.0",
        "header": {"event_id": "e1", "event_type": "im.message.receive_v1", "token": "test-verify-token"},
        "event": {"sender": {"sender_id": {"open_id": "open_smoke"}},
                  "message": {"message_id": "m1", "message_type": "text", "content": '{"text":"hi"}'}},
    }
    r = await client.post("/api/lark/webhook", json=payload_new)
    assert r.status_code == 200
    user = (await session.execute(select(User).where(User.lark_user_id == "open_smoke"))).scalar_one()

    # Step 2: user adds a task
    payload_task = {
        "schema": "2.0",
        "header": {"event_id": "e2", "event_type": "im.message.receive_v1", "token": "test-verify-token"},
        "event": {"sender": {"sender_id": {"open_id": "open_smoke"}},
                  "message": {"message_id": "m2", "message_type": "text", "content": '{"text":"add task fast"}'}},
    }
    r = await client.post("/api/lark/webhook", json=payload_task)
    assert r.status_code == 200
    task = (await session.execute(select(Task).where(Task.user_id == user.id))).scalar_one()
    assert task.title == "fast task"

    # A pending task_checkin_1 should exist
    rems = (await session.execute(select(Reminder).where(Reminder.linked_task_id == task.id))).scalars().all()
    assert any(r.type == "task_checkin_1" and r.status == "pending" for r in rems)

    # Inject task_id into next THINK response
    think_script[0]["actions"][0]["params"]["task_id"] = task.id

    # Step 3: user replies "done"
    payload_done = {
        "schema": "2.0",
        "header": {"event_id": "e3", "event_type": "im.message.receive_v1", "token": "test-verify-token"},
        "event": {"sender": {"sender_id": {"open_id": "open_smoke"}},
                  "message": {"message_id": "m3", "message_type": "text", "content": '{"text":"done"}'}},
    }
    r = await client.post("/api/lark/webhook", json=payload_done)
    assert r.status_code == 200

    await session.refresh(task)
    assert task.status == "done"
    rem1 = (await session.execute(
        select(Reminder).where(Reminder.linked_task_id == task.id, Reminder.type == "task_checkin_1")
    )).scalar_one()
    assert rem1.status == "cancelled"

    events = (await session.execute(select(Event).where(Event.user_id == user.id).order_by(Event.id))).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert "welcome_sent" in types
    assert "task_created" in types
    assert "task_completed" in types
