import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator
from app.orchestrator.triggers import (
    EveningRecapTrigger,
    MorningBriefTrigger,
    TaskCheckinTrigger,
    WelcomeTrigger,
)


class _Router:
    def __init__(self, react_text="ok"):
        self.react_text = react_text
        self.react_task_types = []
        self.react_messages = []
    async def complete(self, task_type, messages, **kw):
        self.react_task_types.append(task_type)
        self.react_messages.append(messages)
        return self.react_text
    async def complete_json(self, task_type, messages, **kw):
        raise AssertionError("THINK should not be called on proactive path")


async def _make_user(session, lark="proactive_u"):
    u = User(name="A", lark_user_id=lark, preferences={})
    session.add(u)
    await session.commit()
    return u


async def test_send_proactive_welcome_starts_flow_and_persists_assistant_msg(session):
    user = await _make_user(session)
    router = _Router(react_text="Hi! Welcome.")
    orch = ConversationOrchestrator(session=session, llm=router)
    out = await orch.send_proactive(
        user_id=user.id,
        trigger=WelcomeTrigger(initial_message="hello"),
        complexity="low",
    )
    assert out == "Hi! Welcome."
    sessions = (await session.execute(select(DialogueSession))).scalars().all()
    assert len(sessions) == 1 and sessions[0].flow_type == "onboarding" and sessions[0].status == "active"
    events = (await session.execute(select(Event))).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types and "welcome_sent" in types
    convs = (await session.execute(select(Conversation))).scalars().all()
    assistant = [c for c in convs if c.role == "assistant"]
    assert len(assistant) == 1 and assistant[0].intent == "proactive:welcome"


async def test_send_proactive_task_checkin_react_only_no_action(session):
    user = await _make_user(session, lark="proactive_u2")
    router = _Router(react_text="搞定了吗？")
    orch = ConversationOrchestrator(session=session, llm=router)
    trigger = TaskCheckinTrigger(
        task_id=42, attempt=1, task_title="写报告", deadline="2026-05-21T14:00:00Z"
    )
    out = await orch.send_proactive(user_id=user.id, trigger=trigger, complexity="low")
    assert "搞定" in out
    events = (await session.execute(select(Event))).scalars().all()
    types = [e.type for e in events]
    assert "task_checkin_sent" in types
    sessions = (await session.execute(select(DialogueSession))).scalars().all()
    assert len(sessions) == 0


async def test_send_proactive_morning_brief_uses_react_model(session):
    user = await _make_user(session, lark="proactive_u3")
    router = _Router(react_text="Morning ☀️")
    orch = ConversationOrchestrator(session=session, llm=router)
    trigger = MorningBriefTrigger(date="2026-05-21", headline_task="x")
    await orch.send_proactive(user_id=user.id, trigger=trigger, complexity="low")
    assert router.react_task_types == ["react"]


async def test_send_proactive_evening_recap_uses_reasoning_model(session):
    user = await _make_user(session, lark="proactive_u4")
    router = _Router(react_text="recap...")
    orch = ConversationOrchestrator(session=session, llm=router)
    trigger = EveningRecapTrigger(date="2026-05-21")
    await orch.send_proactive(user_id=user.id, trigger=trigger, complexity="high")
    assert router.react_task_types == ["reasoning"]


async def test_send_proactive_coach_opening_starts_coach_flow(session):
    user = await _make_user(session, lark="coach_proactive_u1")
    router = _Router(react_text="Hey, I noticed something — want to take a look?")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import CoachOpeningTrigger
    out = await orch.send_proactive(
        user_id=user.id,
        trigger=CoachOpeningTrigger(reason="task X pushed 3 times"),
        complexity="high",
    )
    assert out is not None and "want to take a look" in out

    from sqlalchemy import select
    from app.models.dialogue_session import DialogueSession
    flows = (await session.execute(
        select(DialogueSession).where(DialogueSession.user_id == user.id)
    )).scalars().all()
    assert len(flows) == 1
    assert flows[0].flow_type == "coach"
    assert flows[0].status == "active"

    from app.models.event import Event
    events = (await session.execute(
        select(Event).where(Event.user_id == user.id)
    )).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert "coach_opening_sent" in types


async def test_send_proactive_coach_opening_uses_reasoning_model(session):
    user = await _make_user(session, lark="coach_proactive_u2")
    router = _Router(react_text="reply")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import CoachOpeningTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=CoachOpeningTrigger(reason="negative feedback"),
        complexity="high",
    )
    assert router.react_task_types == ["reasoning"]


async def test_send_proactive_handles_llm_failure_gracefully(session):
    user = await _make_user(session, lark="proactive_u5")

    class _BoomRouter:
        async def complete(self, *a, **kw):
            from app.llm.router import LLMError
            raise LLMError("boom")
        async def complete_json(self, *a, **kw):
            raise AssertionError("not called")

    orch = ConversationOrchestrator(session=session, llm=_BoomRouter())
    out = await orch.send_proactive(
        user_id=user.id, trigger=MorningBriefTrigger(date="2026-05-21"), complexity="low"
    )
    assert out is None
    convs = (await session.execute(select(Conversation))).scalars().all()
    events = (await session.execute(select(Event))).scalars().all()
    assert all(c.role != "assistant" for c in convs)
    assert all(not e.type.endswith("_sent") for e in events)


async def test_send_proactive_attaches_piggyback_from_deferred_checkin(session):
    from datetime import datetime, timedelta, timezone
    from app.models.reminder import Reminder
    from app.models.task import Task

    user = await _make_user(session, lark="piggy_u1")
    task = Task(user_id=user.id, title="写报告", status="pending",
                deadline=datetime.now(timezone.utc) - timedelta(days=2))
    session.add(task)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=1),
        type="task_checkin_3",
        linked_task_id=task.id,
        status="deferred",
        message="",
    )
    session.add(rem)
    await session.commit()

    router = _Router(react_text="Morning! Don't forget 写报告.")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import MorningBriefTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=MorningBriefTrigger(date="2026-05-27", headline_task="something"),
        complexity="low",
    )

    # Piggyback content reached REACT's user content
    user_msg = router.react_messages[0][1]["content"]
    assert "piggyback_checkin" in user_msg
    assert "写报告" in user_msg

    # Reminder is now marked sent (not still deferred)
    await session.refresh(rem)
    assert rem.status == "sent"


async def test_send_proactive_no_piggyback_when_no_deferred(session):
    user = await _make_user(session, lark="piggy_u2")
    router = _Router(react_text="Morning brief.")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import MorningBriefTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=MorningBriefTrigger(date="2026-05-27"),
        complexity="low",
    )
    user_msg = router.react_messages[0][1]["content"]
    assert "piggyback_checkin" not in user_msg


async def test_send_proactive_skips_piggyback_when_task_done(session):
    from datetime import datetime, timedelta, timezone
    from app.models.reminder import Reminder
    from app.models.task import Task

    user = await _make_user(session, lark="piggy_u3")
    task = Task(user_id=user.id, title="finished one", status="done")
    session.add(task)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=1),
        type="task_checkin_3",
        linked_task_id=task.id,
        status="deferred",
        message="",
    )
    session.add(rem)
    await session.commit()

    router = _Router(react_text="ok")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import MorningBriefTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=MorningBriefTrigger(date="2026-05-27"),
        complexity="low",
    )
    user_msg = router.react_messages[0][1]["content"]
    assert "piggyback_checkin" not in user_msg
    # Reminder stays deferred (will expire on its own)
    await session.refresh(rem)
    assert rem.status == "deferred"


async def test_send_proactive_picks_oldest_deferred(session):
    from datetime import datetime, timedelta, timezone
    from app.models.reminder import Reminder
    from app.models.task import Task

    user = await _make_user(session, lark="piggy_u4")
    older_task = Task(user_id=user.id, title="老的任务", status="pending")
    newer_task = Task(user_id=user.id, title="新的任务", status="pending")
    session.add(older_task)
    session.add(newer_task)
    await session.commit()
    older = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=10),
        type="task_checkin_3", linked_task_id=older_task.id,
        status="deferred", message="",
    )
    newer = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=1),
        type="task_checkin_3", linked_task_id=newer_task.id,
        status="deferred", message="",
    )
    session.add(older)
    session.add(newer)
    await session.commit()

    router = _Router(react_text="ok")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import MorningBriefTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=MorningBriefTrigger(date="2026-05-27"),
        complexity="low",
    )
    user_msg = router.react_messages[0][1]["content"]
    assert "老的任务" in user_msg
    assert "新的任务" not in user_msg


async def test_piggyback_works_for_coach_opening_too(session):
    """Piggy-back should attach to any outbound proactive — including coach openings."""
    from datetime import datetime, timedelta, timezone
    from app.models.reminder import Reminder
    from app.models.task import Task

    user = await _make_user(session, lark="piggy_u5")
    task = Task(user_id=user.id, title="lingering", status="pending")
    session.add(task)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=1),
        type="task_checkin_3", linked_task_id=task.id,
        status="deferred", message="",
    )
    session.add(rem)
    await session.commit()

    router = _Router(react_text="coach opens")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import CoachOpeningTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=CoachOpeningTrigger(reason="negative feedback"),
        complexity="high",
    )
    user_msg = router.react_messages[0][1]["content"]
    assert "piggyback_checkin" in user_msg
    assert "lingering" in user_msg
