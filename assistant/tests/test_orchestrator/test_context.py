from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.task import Task
from app.models.user import User
from app.orchestrator.context import load_context


async def test_load_context_minimal_user(session):
    u = User(name="A", lark_user_id="ctx_u1", preferences={})
    session.add(u)
    await session.commit()
    ctx = await load_context(u.id, session)
    assert ctx.user_id == u.id
    assert ctx.user_name == "A"
    assert ctx.profile.name is None
    assert ctx.recent_turns == []
    assert ctx.active_flow is None


async def test_load_context_includes_recent_turns(session):
    u = User(name="B", lark_user_id="ctx_u2", preferences={})
    session.add(u)
    await session.commit()
    for i in range(15):
        session.add(Conversation(user_id=u.id, role="user", content=f"msg{i}"))
    await session.commit()
    ctx = await load_context(u.id, session)
    # New behavior: all of today's turns are returned (capped at 60)
    assert len(ctx.recent_turns) == 15
    assert ctx.recent_turns[-1]["content"] == "msg14"


async def test_load_context_active_flow_with_missing_fields(session):
    u = User(
        name="C",
        lark_user_id="ctx_u3",
        preferences={
            "profile": {"wake_up": "07:00"},
            "procedural": [],
            "onboarding_status": "in_progress",
        },
    )
    session.add(u)
    await session.commit()
    session.add(DialogueSession(user_id=u.id, flow_type="onboarding", status="active"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert ctx.active_flow == "onboarding"
    assert "wake_up" in ctx.flow_filled_fields
    assert any(f.name == "yearly_goals" for f in ctx.flow_missing_fields)


async def test_load_context_open_tasks_capped(session):
    u = User(name="D", lark_user_id="ctx_u4", preferences={})
    session.add(u)
    await session.commit()
    for i in range(8):
        session.add(Task(user_id=u.id, title=f"t{i}", status="pending"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.open_tasks) == 5


from app.models.goal import Goal
from app.models.habit import Habit


async def test_load_context_includes_active_goals(session):
    u = User(name="G", lark_user_id="ctx_g1", preferences={})
    session.add(u)
    await session.commit()
    from datetime import date
    session.add(Goal(
        user_id=u.id, title="run a marathon", target_value=42.0, current_value=0.0,
        unit="km", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), status="active",
    ))
    session.add(Goal(
        user_id=u.id, title="old goal", target_value=1.0, current_value=1.0,
        unit="x", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), status="completed",
    ))
    await session.commit()
    ctx = await load_context(u.id, session)
    titles = [g["title"] for g in ctx.active_goals]
    assert "run a marathon" in titles
    assert "old goal" not in titles


async def test_load_context_includes_active_habits(session):
    u = User(name="H", lark_user_id="ctx_h1", preferences={})
    session.add(u)
    await session.commit()
    session.add(Habit(user_id=u.id, title="morning run", frequency_type="daily", active=True))
    session.add(Habit(user_id=u.id, title="old habit", frequency_type="daily", active=False))
    await session.commit()
    ctx = await load_context(u.id, session)
    titles = [h["title"] for h in ctx.active_habits]
    assert "morning run" in titles
    assert "old habit" not in titles


from datetime import datetime, timedelta, timezone


async def test_load_context_loads_all_of_todays_turns(session):
    u = User(name="T", lark_user_id="ctx_today", preferences={})
    session.add(u)
    await session.commit()
    for i in range(25):
        session.add(Conversation(user_id=u.id, role="user", content=f"today_msg_{i}"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.recent_turns) == 25
    assert ctx.recent_turns[-1]["content"] == "today_msg_24"


async def test_load_context_caps_at_60_turns(session):
    u = User(name="T", lark_user_id="ctx_cap", preferences={})
    session.add(u)
    await session.commit()
    for i in range(80):
        session.add(Conversation(user_id=u.id, role="user", content=f"m_{i}"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.recent_turns) == 60
    # Last item kept
    assert ctx.recent_turns[-1]["content"] == "m_79"


async def test_load_context_has_episodic_recall_field(session):
    u = User(name="T", lark_user_id="ctx_ep", preferences={})
    session.add(u)
    await session.commit()
    ctx = await load_context(u.id, session)
    assert hasattr(ctx, "episodic_recall")
    assert ctx.episodic_recall == []


async def test_load_context_accepts_query_text(session, monkeypatch):
    calls = []
    async def fake_recall(s, user_id, query_text):
        calls.append({"user_id": user_id, "query_text": query_text})
        return []
    monkeypatch.setattr("app.orchestrator.context.episodic_recall", fake_recall)

    u = User(name="T", lark_user_id="ctx_query", preferences={})
    session.add(u)
    await session.commit()
    await load_context(u.id, session, query_text="hello there")
    assert calls and calls[0]["query_text"] == "hello there"


async def test_load_context_blank_query_skips_recall(session, monkeypatch):
    calls = []
    async def fake_recall(s, user_id, query_text):
        calls.append({"user_id": user_id, "query_text": query_text})
        return []
    monkeypatch.setattr("app.orchestrator.context.episodic_recall", fake_recall)

    u = User(name="T", lark_user_id="ctx_noquery", preferences={})
    session.add(u)
    await session.commit()
    await load_context(u.id, session)
    assert calls == []
