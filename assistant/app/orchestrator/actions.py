from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ActionType(str, Enum):
    CREATE_TASK = "create_task"
    UPDATE_TASK = "update_task"
    COMPLETE_TASK = "complete_task"
    DELETE_TASK = "delete_task"
    CREATE_GOAL = "create_goal"
    UPDATE_GOAL = "update_goal"
    ADD_HABIT = "add_habit"
    COMPLETE_HABIT = "complete_habit"
    UPDATE_PROFILE = "update_profile"
    RECORD_PATTERN = "record_pattern"
    RECORD_FEEDBACK = "record_feedback"
    START_FLOW = "start_flow"
    REINFORCE_PATTERN = "reinforce_pattern"
    CONTRADICT_PATTERN = "contradict_pattern"
    END_COACH_SESSION = "end_coach_session"


class CreateTaskParams(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    estimated_minutes: Optional[int] = None
    quadrant: Optional[str] = None
    goal_id: Optional[int] = None
    habit_id: Optional[int] = None


class UpdateTaskParams(BaseModel):
    task_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    estimated_minutes: Optional[int] = None
    quadrant: Optional[str] = None
    status: Optional[str] = None


class CompleteTaskParams(BaseModel):
    task_id: int


class DeleteTaskParams(BaseModel):
    task_id: int


class CreateGoalParams(BaseModel):
    title: str
    target_value: float = 1.0          # default: counter goal (one task = +1)
    unit: str = "count"                # default unit
    period_start: Optional[str] = None # ISO date; default today
    period_end: Optional[str] = None   # ISO date; default today + 365 days


class UpdateGoalParams(BaseModel):
    goal_id: int
    title: Optional[str] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    period_end: Optional[str] = None   # ISO date
    status: Optional[str] = None        # active / completed / cancelled


class AddHabitParams(BaseModel):
    title: str
    frequency_type: str = "daily"      # daily / weekly / etc.
    frequency_count: int = 1
    preferred_time_slots: Optional[list] = None


class CompleteHabitParams(BaseModel):
    habit_id: int
    date: Optional[str] = None


class UpdateProfileParams(BaseModel):
    path: str
    value: object


class RecordPatternParams(BaseModel):
    pattern: str
    confidence: float = 0.5


class ReinforcePatternParams(BaseModel):
    pattern_substring: str
    delta: float = 0.1


class ContradictPatternParams(BaseModel):
    pattern_substring: str
    delta: float = 0.3


class RecordFeedbackParams(BaseModel):
    sentiment: Optional[str] = None
    content: str


class StartFlowParams(BaseModel):
    flow_name: str


class EndCoachSessionParams(BaseModel):
    """No params needed — finds active coach session and ends it."""
    pass


PARAM_REGISTRY: dict[ActionType, type[BaseModel]] = {
    ActionType.CREATE_TASK: CreateTaskParams,
    ActionType.UPDATE_TASK: UpdateTaskParams,
    ActionType.COMPLETE_TASK: CompleteTaskParams,
    ActionType.DELETE_TASK: DeleteTaskParams,
    ActionType.CREATE_GOAL: CreateGoalParams,
    ActionType.UPDATE_GOAL: UpdateGoalParams,
    ActionType.ADD_HABIT: AddHabitParams,
    ActionType.COMPLETE_HABIT: CompleteHabitParams,
    ActionType.UPDATE_PROFILE: UpdateProfileParams,
    ActionType.RECORD_PATTERN: RecordPatternParams,
    ActionType.RECORD_FEEDBACK: RecordFeedbackParams,
    ActionType.START_FLOW: StartFlowParams,
    ActionType.REINFORCE_PATTERN: ReinforcePatternParams,
    ActionType.CONTRADICT_PATTERN: ContradictPatternParams,
    ActionType.END_COACH_SESSION: EndCoachSessionParams,
}


@dataclass
class ParsedAction:
    type: ActionType
    params: BaseModel


def parse_action(raw: dict) -> ParsedAction:
    type_str = raw.get("type")
    if not type_str:
        raise ValueError("action missing 'type'")
    try:
        action_type = ActionType(type_str)
    except ValueError as e:
        raise ValueError(f"unknown action type: {type_str}") from e
    schema = PARAM_REGISTRY[action_type]
    params = schema.model_validate(raw.get("params", {}))
    return ParsedAction(type=action_type, params=params)
