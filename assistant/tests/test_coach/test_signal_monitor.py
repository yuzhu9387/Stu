import pytest
from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.task import Task
from app.models.user import User


async def test_detect_trigger_3day_silence(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_silence_u", preferences={})
    session.add(user)
    await session.commit()
    old = Conversation(user_id=user.id, role="user", content="hi")
    session.add(old)
    await session.commit()
    old.created_at = datetime.now(timezone.utc) - timedelta(days=4)
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is not None
    assert "days" in reason.lower() or "haven't" in reason.lower()


async def test_detect_trigger_no_silence_when_recent(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_recent_u", preferences={})
    session.add(user)
    await session.commit()
    msg = Conversation(user_id=user.id, role="user", content="hi")
    session.add(msg)
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is None


async def test_detect_trigger_negative_feedback(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_neg_u", preferences={})
    session.add(user)
    await session.commit()
    session.add(Conversation(user_id=user.id, role="user", content="hi"))
    session.add(Event(
        user_id=user.id, type="feedback_recorded",
        entity_type="feedback", entity_id=None,
        payload={"sentiment": "negative", "content": "this isn't helping"},
    ))
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is not None
    assert "happy" in reason.lower() or "feedback" in reason.lower() or "went" in reason.lower()


async def test_detect_trigger_3x_deferred_task(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_defer_u", preferences={})
    session.add(user)
    await session.commit()
    session.add(Conversation(user_id=user.id, role="user", content="hi"))
    task = Task(user_id=user.id, title="write report", status="pending",
                deadline=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(task)
    await session.commit()
    for i in range(3):
        session.add(Event(
            user_id=user.id, type="task_updated",
            entity_type="task", entity_id=task.id,
            payload={
                "before": {"deadline": f"2026-05-{20+i}T00:00:00+00:00"},
                "after": {"deadline": f"2026-05-{21+i}T00:00:00+00:00"},
            },
        ))
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is not None
    assert "write report" in reason


async def test_detect_trigger_no_signal_returns_none(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_clean_u", preferences={})
    session.add(user)
    await session.commit()
    session.add(Conversation(user_id=user.id, role="user", content="hi"))
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is None


async def test_recently_in_coach_true_when_session_within_24h(session):
    from app.coach.signal_monitor import _recently_in_coach

    user = User(name="A", lark_user_id="sig_recent_coach_u", preferences={})
    session.add(user)
    await session.commit()
    sess = DialogueSession(user_id=user.id, flow_type="coach", status="completed")
    session.add(sess)
    await session.commit()

    assert await _recently_in_coach(session, user.id, hours=24) is True


async def test_recently_in_coach_false_when_no_session(session):
    from app.coach.signal_monitor import _recently_in_coach

    user = User(name="A", lark_user_id="sig_no_coach_u", preferences={})
    session.add(user)
    await session.commit()

    assert await _recently_in_coach(session, user.id, hours=24) is False
