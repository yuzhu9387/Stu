import pytest
from datetime import date as date_type
from sqlalchemy import select

from app.models.goal import Goal
from app.models.task import Task
from app.models.user import User


async def test_create_complete_increments_goal(client, session, monkeypatch):
    """E2E: user creates a goal-linked task, completes it via THINK action, goal goes up."""

    user = User(name="X", lark_user_id="mem_e2e_u1", preferences={})
    session.add(user)
    await session.commit()
    goal = Goal(
        user_id=user.id, title="post 12 blogs", target_value=12, current_value=0,
        unit="post", period_start=date_type.today(), period_end=date_type.today(),
        status="active",
    )
    session.add(goal)
    await session.commit()

    think_script = [
        {
            "intent": "add task tied to goal",
            "actions": [{"type": "create_task", "params": {"title": "blog 1", "goal_id": goal.id}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "confirm", "reasoning": "",
        },
        {
            "intent": "user reports done",
            "actions": [{"type": "complete_task", "params": {"task_id": None}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "celebrate", "reasoning": "",
        },
    ]
    react_script = ["Got it.", "Nice 🎉"]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return think_script.pop(0)
        async def complete(self, task_type, messages, **kw):
            return react_script.pop(0)
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _Router)

    r = await client.post("/api/conversation", json={"user_id": user.id, "message": "add blog 1"})
    assert r.status_code == 200
    task = (await session.execute(select(Task).where(Task.user_id == user.id))).scalar_one()
    assert task.goal_id == goal.id

    think_script[0]["actions"][0]["params"]["task_id"] = task.id
    r = await client.post("/api/conversation", json={"user_id": user.id, "message": "done"})
    assert r.status_code == 200

    await session.refresh(goal)
    assert goal.current_value == 1
