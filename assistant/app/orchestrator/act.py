from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.memory.confidence import _clamp
from app.memory.embeddings import EMBEDDABLE_EVENT_TYPES, embed_and_store
from app.models.event import Event
from app.models.goal import Goal
from app.models.habit import Habit
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.models.dialogue_session import DialogueSession
from app.orchestrator.actions import (
    ActionType,
    AddHabitParams,
    CompleteHabitParams,
    CompleteTaskParams,
    ContradictPatternParams,
    CreateGoalParams,
    CreateTaskParams,
    DeleteTaskParams,
    EndCoachSessionParams,
    ParsedAction,
    RecordFeedbackParams,
    RecordPatternParams,
    ReinforcePatternParams,
    StartFlowParams,
    UpdateGoalParams,
    UpdateProfileParams,
    UpdateTaskParams,
)


def _content_for_event(action_type: str, payload: dict) -> str:
    """Build embeddable text for a result row."""
    if action_type == "task_completed":
        return f"completed task: {payload.get('title', '')}".strip()
    if action_type == "pattern_recorded":
        return f"learned pattern: {payload.get('pattern', '')}".strip()
    if action_type == "profile_updated":
        return f"profile {payload.get('path', '')}: {payload.get('after', '')}".strip()
    if action_type == "feedback_recorded":
        return str(payload.get("content", "")).strip()
    if action_type == "goal_set":
        return f"goal: {payload.get('title', '')}".strip()
    return ""


async def _background_embed_event(user_id: int, source_id: int, content: str) -> None:
    if not content:
        return
    async with async_session_factory() as session:
        await embed_and_store(session, user_id, "event", source_id, content)


@dataclass
class ActionResult:
    type: ActionType
    entity_type: Optional[str]
    entity_id: Optional[int]
    payload: dict


class ActionExecutor:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute_all(
        self,
        user_id: int,
        actions: list[ParsedAction],
        conversation_id: Optional[int],
    ) -> list[ActionResult]:
        if not actions:
            return []
        async with self.session.begin_nested():
            results: list[ActionResult] = []
            for action in actions:
                result = await self._dispatch(user_id, action)
                event = Event(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    type=_event_type_for(action.type),
                    entity_type=result.entity_type,
                    entity_id=result.entity_id,
                    payload=result.payload,
                )
                self.session.add(event)
                results.append(result)
        await self.session.commit()

        # Fire-and-forget embedding writes for embeddable event types.
        for result, action in zip(results, actions):
            event_type = _EVENT_TYPE_MAP.get(action.type)
            if event_type in EMBEDDABLE_EVENT_TYPES:
                content = _content_for_event(event_type, result.payload or {})
                if content and result.entity_id is not None:
                    asyncio.create_task(
                        _background_embed_event(user_id, result.entity_id, content)
                    )
        return results

    async def _dispatch(self, user_id: int, action: ParsedAction) -> ActionResult:
        params = action.params
        if action.type == ActionType.CREATE_TASK:
            return await self._create_task(user_id, params)
        if action.type == ActionType.UPDATE_TASK:
            return await self._update_task(user_id, params)
        if action.type == ActionType.COMPLETE_TASK:
            return await self._complete_task(user_id, params)
        if action.type == ActionType.DELETE_TASK:
            return await self._delete_task(user_id, params)
        if action.type == ActionType.CREATE_GOAL:
            return await self._create_goal(user_id, params)
        if action.type == ActionType.UPDATE_GOAL:
            return await self._update_goal(user_id, params)
        if action.type == ActionType.ADD_HABIT:
            return await self._add_habit(user_id, params)
        if action.type == ActionType.COMPLETE_HABIT:
            return await self._complete_habit(user_id, params)
        if action.type == ActionType.UPDATE_PROFILE:
            return await self._update_profile(user_id, params)
        if action.type == ActionType.RECORD_PATTERN:
            return await self._record_pattern(user_id, params)
        if action.type == ActionType.RECORD_FEEDBACK:
            return await self._record_feedback(user_id, params)
        if action.type == ActionType.START_FLOW:
            return await self._start_flow(user_id, params)
        if action.type == ActionType.REINFORCE_PATTERN:
            return await self._reinforce_pattern(user_id, params)
        if action.type == ActionType.CONTRADICT_PATTERN:
            return await self._contradict_pattern(user_id, params)
        if action.type == ActionType.END_COACH_SESSION:
            return await self._end_coach_session(user_id, params)
        raise ValueError(f"unhandled action type: {action.type}")

    async def _create_task(self, user_id: int, p: CreateTaskParams) -> ActionResult:
        task = Task(
            user_id=user_id,
            title=p.title,
            description=p.description,
            deadline=_parse_iso_datetime(p.deadline),
            quadrant=p.quadrant,
            goal_id=p.goal_id,
            habit_id=p.habit_id,
        )
        self.session.add(task)
        await self.session.flush()
        if task.deadline is not None:
            self.session.add(Reminder(
                user_id=user_id,
                trigger_time=task.deadline + timedelta(minutes=15),
                type="task_checkin_1",
                linked_task_id=task.id,
                status="pending",
                message="",
            ))
            await self.session.flush()
        return ActionResult(
            type=ActionType.CREATE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"title": task.title, "deadline": p.deadline, "quadrant": p.quadrant},
        )

    async def _update_task(self, user_id: int, p: UpdateTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        before = {"title": task.title, "status": task.status}
        if p.title is not None: task.title = p.title
        if p.description is not None: task.description = p.description
        if p.deadline is not None: task.deadline = _parse_iso_datetime(p.deadline)
        if p.quadrant is not None: task.quadrant = p.quadrant
        if p.status is not None: task.status = p.status
        await self.session.flush()
        return ActionResult(
            type=ActionType.UPDATE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"before": before, "after": {"title": task.title, "status": task.status}},
        )

    async def _complete_task(self, user_id: int, p: CompleteTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        task.status = "done"
        await self.session.execute(
            update(Reminder)
            .where(Reminder.linked_task_id == p.task_id, Reminder.status == "pending")
            .values(status="cancelled")
        )
        # NEW: increment linked goal
        goal_incremented = False
        if task.goal_id is not None:
            goal = await self.session.get(Goal, task.goal_id)
            if goal is not None and goal.status == "active":
                goal.current_value = (goal.current_value or 0) + 1
                goal_incremented = True
        await self.session.flush()
        return ActionResult(
            type=ActionType.COMPLETE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"completed_at": _now_iso(), "goal_incremented": goal_incremented},
        )

    async def _delete_task(self, user_id: int, p: DeleteTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        snapshot = {"title": task.title, "status": task.status}
        await self.session.delete(task)
        await self.session.flush()
        return ActionResult(
            type=ActionType.DELETE_TASK,
            entity_type="task",
            entity_id=p.task_id,
            payload=snapshot,
        )

    async def _create_goal(self, user_id: int, p: CreateGoalParams) -> ActionResult:
        period_start = (
            date_type.fromisoformat(p.period_start) if p.period_start
            else date_type.today()
        )
        period_end = (
            date_type.fromisoformat(p.period_end) if p.period_end
            else period_start + timedelta(days=365)
        )
        goal = Goal(
            user_id=user_id,
            title=p.title,
            target_value=p.target_value,
            unit=p.unit,
            period_start=period_start,
            period_end=period_end,
        )
        self.session.add(goal)
        await self.session.flush()
        return ActionResult(
            type=ActionType.CREATE_GOAL,
            entity_type="goal",
            entity_id=goal.id,
            payload={
                "title": goal.title,
                "target_value": p.target_value,
                "unit": p.unit,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )

    async def _update_goal(self, user_id: int, p: UpdateGoalParams) -> ActionResult:
        goal = await self.session.get(Goal, p.goal_id)
        if goal is None or goal.user_id != user_id:
            raise ValueError(f"goal {p.goal_id} not found")
        before = {
            "title": goal.title,
            "target_value": goal.target_value,
            "current_value": goal.current_value,
            "unit": goal.unit,
            "period_end": goal.period_end.isoformat() if goal.period_end else None,
            "status": goal.status,
        }
        if p.title is not None:
            goal.title = p.title
        if p.target_value is not None:
            goal.target_value = p.target_value
        if p.current_value is not None:
            goal.current_value = p.current_value
        if p.unit is not None:
            goal.unit = p.unit
        if p.period_end is not None:
            goal.period_end = date_type.fromisoformat(p.period_end)
        if p.status is not None:
            goal.status = p.status
        await self.session.flush()
        after = {
            "title": goal.title,
            "target_value": goal.target_value,
            "current_value": goal.current_value,
            "unit": goal.unit,
            "period_end": goal.period_end.isoformat() if goal.period_end else None,
            "status": goal.status,
        }
        return ActionResult(
            type=ActionType.UPDATE_GOAL,
            entity_type="goal",
            entity_id=goal.id,
            payload={"before": before, "after": after},
        )

    async def _add_habit(self, user_id: int, p: AddHabitParams) -> ActionResult:
        habit = Habit(
            user_id=user_id,
            title=p.title,
            frequency_type=p.frequency_type,
            frequency_count=p.frequency_count,
        )
        if p.preferred_time_slots is not None:
            habit.preferred_time_slots = p.preferred_time_slots
        self.session.add(habit)
        await self.session.flush()
        return ActionResult(
            type=ActionType.ADD_HABIT,
            entity_type="habit",
            entity_id=habit.id,
            payload={
                "title": habit.title,
                "frequency_type": p.frequency_type,
                "frequency_count": p.frequency_count,
            },
        )

    async def _complete_habit(self, user_id: int, p: CompleteHabitParams) -> ActionResult:
        habit = await self.session.get(Habit, p.habit_id)
        if habit is None or habit.user_id != user_id:
            raise ValueError(f"habit {p.habit_id} not found")
        return ActionResult(
            type=ActionType.COMPLETE_HABIT,
            entity_type="habit",
            entity_id=habit.id,
            payload={"date": p.date or date_type.today().isoformat()},
        )

    async def _update_profile(self, user_id: int, p: UpdateProfileParams) -> ActionResult:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        prefs = dict(user.preferences or {})
        profile = dict(prefs.get("profile", {}))
        before = profile.get(p.path)
        profile[p.path] = p.value
        prefs["profile"] = profile
        user.preferences = prefs
        await self.session.flush()
        return ActionResult(
            type=ActionType.UPDATE_PROFILE,
            entity_type="profile",
            entity_id=None,
            payload={"path": p.path, "before": before, "after": p.value},
        )

    async def _record_pattern(self, user_id: int, p: RecordPatternParams) -> ActionResult:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        prefs = dict(user.preferences or {})
        patterns = list(prefs.get("procedural", []))
        patterns.append({"pattern": p.pattern, "confidence": p.confidence, "learned_at": _now_iso()})
        prefs["procedural"] = patterns
        user.preferences = prefs
        await self.session.flush()
        return ActionResult(
            type=ActionType.RECORD_PATTERN,
            entity_type="pattern",
            entity_id=None,
            payload={"pattern": p.pattern, "confidence": p.confidence},
        )

    async def _record_feedback(self, user_id: int, p: RecordFeedbackParams) -> ActionResult:
        return ActionResult(
            type=ActionType.RECORD_FEEDBACK,
            entity_type="feedback",
            entity_id=None,
            payload={"sentiment": p.sentiment, "content": p.content},
        )

    async def _start_flow(self, user_id: int, p: StartFlowParams) -> ActionResult:
        ds = DialogueSession(user_id=user_id, flow_type=p.flow_name, status="active")
        self.session.add(ds)
        await self.session.flush()
        return ActionResult(
            type=ActionType.START_FLOW,
            entity_type="flow",
            entity_id=ds.id,
            payload={"flow_name": p.flow_name},
        )

    async def _end_coach_session(
        self, user_id: int, p: EndCoachSessionParams
    ) -> ActionResult:
        q = (
            select(DialogueSession)
            .where(
                DialogueSession.user_id == user_id,
                DialogueSession.flow_type == "coach",
                DialogueSession.status == "active",
            )
            .order_by(desc(DialogueSession.id))
            .limit(1)
        )
        sess = (await self.session.execute(q)).scalar_one_or_none()
        if sess is None:
            return ActionResult(
                type=ActionType.END_COACH_SESSION,
                entity_type="flow",
                entity_id=None,
                payload={"ended": False, "reason": "no active coach session"},
            )
        sess.status = "completed"
        await self.session.flush()
        return ActionResult(
            type=ActionType.END_COACH_SESSION,
            entity_type="flow",
            entity_id=sess.id,
            payload={"ended": True, "session_id": sess.id},
        )

    async def _reinforce_pattern(
        self, user_id: int, p: ReinforcePatternParams
    ) -> ActionResult:
        return await self._adjust_pattern(
            user_id, p.pattern_substring, +abs(p.delta),
            action_type=ActionType.REINFORCE_PATTERN,
        )

    async def _contradict_pattern(
        self, user_id: int, p: ContradictPatternParams
    ) -> ActionResult:
        return await self._adjust_pattern(
            user_id, p.pattern_substring, -abs(p.delta),
            action_type=ActionType.CONTRADICT_PATTERN,
        )

    async def _adjust_pattern(
        self,
        user_id: int,
        substring: str,
        delta: float,
        action_type: ActionType,
    ) -> ActionResult:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        prefs = dict(user.preferences or {})
        procedural = list(prefs.get("procedural", []))
        match_idx = None
        for i, pat in enumerate(procedural):
            if substring.lower() in pat.get("pattern", "").lower():
                match_idx = i
                break
        if match_idx is None:
            # No match — emit a no-op result
            return ActionResult(
                type=action_type, entity_type="pattern", entity_id=None,
                payload={"matched": False, "substring": substring, "delta": delta},
            )
        target = dict(procedural[match_idx])
        old_conf = float(target.get("confidence", 0.5))
        new_conf = _clamp(old_conf + delta)
        target["confidence"] = new_conf
        target["last_reinforced_at"] = _now_iso()
        procedural[match_idx] = target
        prefs["procedural"] = procedural
        user.preferences = prefs
        await self.session.flush()
        return ActionResult(
            type=action_type, entity_type="pattern", entity_id=None,
            payload={"matched": True, "substring": substring,
                     "before_confidence": old_conf, "after_confidence": new_conf},
        )


_EVENT_TYPE_MAP: dict[ActionType, str] = {
    ActionType.CREATE_TASK: "task_created",
    ActionType.UPDATE_TASK: "task_updated",
    ActionType.COMPLETE_TASK: "task_completed",
    ActionType.DELETE_TASK: "task_deleted",
    ActionType.CREATE_GOAL: "goal_set",
    ActionType.UPDATE_GOAL: "goal_updated",
    ActionType.ADD_HABIT: "habit_added",
    ActionType.COMPLETE_HABIT: "habit_completed",
    ActionType.UPDATE_PROFILE: "profile_updated",
    ActionType.RECORD_PATTERN: "pattern_recorded",
    ActionType.RECORD_FEEDBACK: "feedback_recorded",
    ActionType.START_FLOW: "flow_started",
    ActionType.REINFORCE_PATTERN: "pattern_reinforced",
    ActionType.CONTRADICT_PATTERN: "pattern_contradicted",
    ActionType.END_COACH_SESSION: "flow_completed",
}


def _event_type_for(action_type: ActionType) -> str:
    return _EVENT_TYPE_MAP[action_type]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # fallback: treat as date
        try:
            d = date_type.fromisoformat(s)
            return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
        except ValueError:
            return None
