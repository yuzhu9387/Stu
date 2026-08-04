import pytest
from sqlalchemy import select

from app.models.event import Event
from app.models.task import Task
from app.models.user import User
from app.orchestrator.act import ActionExecutor
from app.orchestrator.actions import (
    ActionType,
    AddHabitParams,
    CompleteTaskParams,
    CreateGoalParams,
    CreateTaskParams,
    ParsedAction,
    RecordPatternParams,
    UpdateGoalParams,
    UpdateProfileParams,
)
from app.orchestrator.actions import ReinforcePatternParams, ContradictPatternParams


async def _make_user(session, name="A", lark="act_u"):
    u = User(name=name, lark_user_id=lark, preferences={})
    session.add(u)
    await session.commit()
    return u


async def test_create_task_action_writes_task_and_event(session):
    user = await _make_user(session)
    executor = ActionExecutor(session)
    actions = [ParsedAction(ActionType.CREATE_TASK, CreateTaskParams(title="x"))]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    assert results[0].entity_type == "task"
    assert results[0].entity_id is not None

    tasks = (await session.execute(select(Task))).scalars().all()
    assert len(tasks) == 1 and tasks[0].title == "x"
    events = (await session.execute(select(Event))).scalars().all()
    assert len(events) == 1
    assert events[0].type == "task_created"
    assert events[0].entity_id == tasks[0].id


async def test_update_profile_writes_jsonb_and_event(session):
    user = await _make_user(session, lark="act_u2")
    executor = ActionExecutor(session)
    actions = [
        ParsedAction(ActionType.UPDATE_PROFILE, UpdateProfileParams(path="diet", value="vegetarian"))
    ]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(user)
    assert user.preferences["profile"]["diet"] == "vegetarian"
    events = (await session.execute(select(Event))).scalars().all()
    assert events[0].type == "profile_updated"
    assert events[0].payload["path"] == "diet"
    assert events[0].payload["after"] == "vegetarian"


async def test_record_pattern_appends_and_event(session):
    user = await _make_user(session, lark="act_u3")
    executor = ActionExecutor(session)
    actions = [
        ParsedAction(ActionType.RECORD_PATTERN, RecordPatternParams(pattern="no 7am pings", confidence=0.8))
    ]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(user)
    patterns = user.preferences["procedural"]
    assert len(patterns) == 1 and patterns[0]["pattern"] == "no 7am pings"
    events = (await session.execute(select(Event))).scalars().all()
    assert events[0].type == "pattern_recorded"


async def test_complete_task_marks_status_and_event(session):
    user = await _make_user(session, lark="act_u4")
    t = Task(user_id=user.id, title="t", status="pending")
    session.add(t)
    await session.commit()
    executor = ActionExecutor(session)
    actions = [ParsedAction(ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=t.id))]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(t)
    assert t.status == "done"
    events = (await session.execute(select(Event))).scalars().all()
    assert events[0].type == "task_completed"


async def test_failed_action_rolls_back_all(session):
    user = await _make_user(session, lark="act_u5")
    executor = ActionExecutor(session)
    actions = [
        ParsedAction(ActionType.CREATE_TASK, CreateTaskParams(title="good")),
        ParsedAction(ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=99999)),
    ]
    with pytest.raises(Exception):
        await executor.execute_all(user.id, actions, conversation_id=None)
    tasks = (await session.execute(select(Task))).scalars().all()
    events = (await session.execute(select(Event))).scalars().all()
    assert len(tasks) == 0
    assert len(events) == 0


from datetime import datetime, timedelta, timezone

from app.models.reminder import Reminder


async def test_create_task_with_deadline_schedules_checkin_1(session):
    user = await _make_user(session, lark="ckin_u1")
    executor = ActionExecutor(session)
    deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    actions = [ParsedAction(
        ActionType.CREATE_TASK, CreateTaskParams(title="x", deadline=deadline_iso)
    )]
    await executor.execute_all(user.id, actions, conversation_id=None)
    rems = (await session.execute(select(Reminder))).scalars().all()
    assert len(rems) == 1
    assert rems[0].type == "task_checkin_1"
    assert rems[0].status == "pending"
    assert rems[0].linked_task_id is not None


async def test_create_task_without_deadline_no_reminder(session):
    user = await _make_user(session, lark="ckin_u2")
    executor = ActionExecutor(session)
    actions = [ParsedAction(ActionType.CREATE_TASK, CreateTaskParams(title="x"))]
    await executor.execute_all(user.id, actions, conversation_id=None)
    rems = (await session.execute(select(Reminder))).scalars().all()
    assert len(rems) == 0


async def test_complete_task_cancels_pending_reminders(session):
    user = await _make_user(session, lark="ckin_u3")
    t = Task(user_id=user.id, title="t", status="pending",
             deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    session.add(t)
    await session.commit()
    rem = Reminder(
        user_id=user.id, trigger_time=datetime.now(timezone.utc) + timedelta(hours=2),
        type="task_checkin_1", linked_task_id=t.id, status="pending", message=""
    )
    session.add(rem)
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=t.id)
    )], conversation_id=None)
    await session.refresh(rem)
    assert rem.status == "cancelled"


from datetime import date as date_type
from app.models.goal import Goal


async def test_complete_task_increments_linked_goal(session):
    user = await _make_user(session, lark="goal_inc_u1")
    goal = Goal(
        user_id=user.id, title="write 50 posts", target_value=50, current_value=3,
        unit="post", period_start=date_type.today(), period_end=date_type.today(),
        status="active",
    )
    session.add(goal)
    await session.commit()
    task = Task(user_id=user.id, title="post 4", status="pending", goal_id=goal.id)
    session.add(task)
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=task.id)
    )], conversation_id=None)
    await session.refresh(goal)
    assert goal.current_value == 4


async def test_complete_task_without_goal_id_does_not_touch_goals(session):
    user = await _make_user(session, lark="goal_inc_u2")
    task = Task(user_id=user.id, title="standalone", status="pending", goal_id=None)
    session.add(task)
    await session.commit()
    executor = ActionExecutor(session)
    # No goals in DB at all - should not error
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=task.id)
    )], conversation_id=None)
    await session.refresh(task)
    assert task.status == "done"


async def test_complete_task_skips_inactive_goal(session):
    user = await _make_user(session, lark="goal_inc_u3")
    goal = Goal(
        user_id=user.id, title="old goal", target_value=10, current_value=8,
        unit="x", period_start=date_type.today(), period_end=date_type.today(),
        status="completed",
    )
    session.add(goal)
    await session.commit()
    task = Task(user_id=user.id, title="leftover", status="pending", goal_id=goal.id)
    session.add(task)
    await session.commit()
    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=task.id)
    )], conversation_id=None)
    await session.refresh(goal)
    assert goal.current_value == 8   # unchanged


async def test_reinforce_pattern_bumps_confidence_and_refreshes_timestamp(session):
    user = await _make_user(session, lark="reinforce_u1")
    user.preferences = {
        "profile": {},
        "procedural": [
            {"pattern": "user dislikes 7am reminders", "confidence": 0.5,
             "learned_at": "2026-05-20T10:00:00+00:00",
             "last_reinforced_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.REINFORCE_PATTERN,
        ReinforcePatternParams(pattern_substring="7am reminders", delta=0.2),
    )], conversation_id=None)
    await session.refresh(user)
    assert user.preferences["procedural"][0]["confidence"] == pytest.approx(0.7)
    assert user.preferences["procedural"][0]["last_reinforced_at"] != "2026-05-20T10:00:00+00:00"


async def test_contradict_pattern_lowers_confidence(session):
    user = await _make_user(session, lark="contradict_u1")
    user.preferences = {
        "profile": {},
        "procedural": [
            {"pattern": "user prefers morning workouts", "confidence": 0.8,
             "learned_at": "2026-05-20T10:00:00+00:00",
             "last_reinforced_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.CONTRADICT_PATTERN,
        ContradictPatternParams(pattern_substring="morning workouts", delta=0.3),
    )], conversation_id=None)
    await session.refresh(user)
    assert user.preferences["procedural"][0]["confidence"] == pytest.approx(0.5)


async def test_clamp_helper():
    """Confidence clamp logic in memory/confidence.py."""
    from app.memory.confidence import _clamp
    assert _clamp(1.5) == 1.0
    assert _clamp(-0.2) == 0.0
    assert _clamp(0.7) == 0.7


async def test_reinforce_pattern_no_match_is_noop(session):
    user = await _make_user(session, lark="reinforce_u2")
    user.preferences = {
        "profile": {},
        "procedural": [
            {"pattern": "user likes coffee", "confidence": 0.5,
             "learned_at": "2026-05-20T10:00:00+00:00",
             "last_reinforced_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    await session.commit()
    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.REINFORCE_PATTERN,
        ReinforcePatternParams(pattern_substring="nonexistent topic", delta=0.2),
    )], conversation_id=None)
    await session.refresh(user)
    assert user.preferences["procedural"][0]["confidence"] == 0.5  # unchanged


from app.models.dialogue_session import DialogueSession
from app.orchestrator.actions import EndCoachSessionParams


async def test_end_coach_session_closes_active_session(session):
    user = await _make_user(session, lark="coach_end_u1")
    s = DialogueSession(user_id=user.id, flow_type="coach", status="active")
    session.add(s)
    await session.commit()
    await session.refresh(s)

    executor = ActionExecutor(session)
    await executor.execute_all(
        user.id,
        [ParsedAction(ActionType.END_COACH_SESSION, EndCoachSessionParams())],
        conversation_id=None,
    )
    await session.refresh(s)
    assert s.status == "completed"


async def test_end_coach_session_no_active_session_is_noop(session):
    user = await _make_user(session, lark="coach_end_u2")
    executor = ActionExecutor(session)
    results = await executor.execute_all(
        user.id,
        [ParsedAction(ActionType.END_COACH_SESSION, EndCoachSessionParams())],
        conversation_id=None,
    )
    assert results[0].type == ActionType.END_COACH_SESSION
    assert results[0].payload.get("ended") is False


async def test_end_coach_session_ignores_non_coach_flows(session):
    user = await _make_user(session, lark="coach_end_u3")
    s = DialogueSession(user_id=user.id, flow_type="onboarding", status="active")
    session.add(s)
    await session.commit()
    await session.refresh(s)

    executor = ActionExecutor(session)
    results = await executor.execute_all(
        user.id,
        [ParsedAction(ActionType.END_COACH_SESSION, EndCoachSessionParams())],
        conversation_id=None,
    )
    await session.refresh(s)
    assert s.status == "active"  # onboarding untouched
    assert results[0].payload.get("ended") is False


async def test_create_goal_with_defaults_persists_row(session):
    user = await _make_user(session, lark="create_goal_u1")
    executor = ActionExecutor(session)
    actions = [ParsedAction(
        ActionType.CREATE_GOAL,
        CreateGoalParams(title="learn rust"),
    )]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    assert results[0].entity_type == "goal"
    assert results[0].entity_id is not None
    from app.models.goal import Goal
    goal = await session.get(Goal, results[0].entity_id)
    assert goal.title == "learn rust"
    assert goal.target_value == 1.0
    assert goal.unit == "count"
    assert goal.period_start is not None
    assert goal.period_end is not None
    # default period: today → +365 days
    assert (goal.period_end - goal.period_start).days == 365


async def test_create_goal_with_explicit_quantitative_fields(session):
    user = await _make_user(session, lark="create_goal_u2")
    executor = ActionExecutor(session)
    actions = [ParsedAction(
        ActionType.CREATE_GOAL,
        CreateGoalParams(
            title="run a marathon",
            target_value=42.2,
            unit="km",
            period_start="2026-01-01",
            period_end="2026-12-31",
        ),
    )]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    from app.models.goal import Goal
    goal = await session.get(Goal, results[0].entity_id)
    assert goal.target_value == 42.2
    assert goal.unit == "km"
    assert goal.period_start.isoformat() == "2026-01-01"
    assert goal.period_end.isoformat() == "2026-12-31"


async def test_add_habit_sets_frequency_type(session):
    user = await _make_user(session, lark="add_habit_u1")
    executor = ActionExecutor(session)
    actions = [ParsedAction(
        ActionType.ADD_HABIT,
        AddHabitParams(title="morning run"),
    )]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    assert results[0].entity_type == "habit"
    from app.models.habit import Habit
    habit = await session.get(Habit, results[0].entity_id)
    assert habit.title == "morning run"
    assert habit.frequency_type == "daily"   # default
    assert habit.frequency_count == 1


async def test_add_habit_weekly_with_count(session):
    user = await _make_user(session, lark="add_habit_u2")
    executor = ActionExecutor(session)
    actions = [ParsedAction(
        ActionType.ADD_HABIT,
        AddHabitParams(title="weekly review", frequency_type="weekly", frequency_count=1),
    )]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    from app.models.habit import Habit
    habit = await session.get(Habit, results[0].entity_id)
    assert habit.frequency_type == "weekly"
    assert habit.frequency_count == 1


async def test_update_goal_changes_target_value(session):
    user = await _make_user(session, lark="upd_goal_u1")
    from datetime import date as date_type
    from app.models.goal import Goal
    goal = Goal(
        user_id=user.id, title="learn rust", target_value=10, current_value=2,
        unit="hours", period_start=date_type.today(), period_end=date_type.today(),
        status="active",
    )
    session.add(goal)
    await session.commit()

    executor = ActionExecutor(session)
    actions = [ParsedAction(
        ActionType.UPDATE_GOAL,
        UpdateGoalParams(goal_id=goal.id, target_value=20),
    )]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(goal)
    assert goal.target_value == 20
    # before/after both captured
    payload = results[0].payload
    assert payload["before"]["target_value"] == 10
    assert payload["after"]["target_value"] == 20


async def test_update_goal_can_mark_complete(session):
    user = await _make_user(session, lark="upd_goal_u2")
    from datetime import date as date_type
    from app.models.goal import Goal
    goal = Goal(
        user_id=user.id, title="x", target_value=1, current_value=0,
        unit="count", period_start=date_type.today(), period_end=date_type.today(),
        status="active",
    )
    session.add(goal)
    await session.commit()

    executor = ActionExecutor(session)
    actions = [ParsedAction(
        ActionType.UPDATE_GOAL,
        UpdateGoalParams(goal_id=goal.id, status="completed"),
    )]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(goal)
    assert goal.status == "completed"
