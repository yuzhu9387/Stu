from __future__ import annotations
import json
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class WelcomeTrigger(BaseModel):
    type: Literal["welcome"] = "welcome"
    initial_message: Optional[str] = None


class TaskCheckinTrigger(BaseModel):
    type: Literal["task_checkin"] = "task_checkin"
    task_id: int
    attempt: int  # 1, 2, or 3
    task_title: str
    deadline: str  # ISO-8601 string
    piggyback_with: Optional["TaskCheckinTrigger"] = None


class MorningBriefTrigger(BaseModel):
    type: Literal["morning_brief"] = "morning_brief"
    date: str
    today_plan: list[dict] = Field(default_factory=list)
    headline_task: Optional[str] = None
    habits_today: list[dict] = Field(default_factory=list)
    active_goals_brief: list[dict] = Field(default_factory=list)


class EveningRecapTrigger(BaseModel):
    type: Literal["evening_recap"] = "evening_recap"
    date: str
    tasks_completed: list[dict] = Field(default_factory=list)
    tasks_missed: list[dict] = Field(default_factory=list)
    habits_done: list[dict] = Field(default_factory=list)
    habits_missed: list[dict] = Field(default_factory=list)
    goals_touched: list[dict] = Field(default_factory=list)
    recent_pattern: dict = Field(default_factory=dict)
    user_feedback_today: list[dict] = Field(default_factory=list)


class CoachOpeningTrigger(BaseModel):
    type: Literal["coach_opening"] = "coach_opening"
    reason: str


Trigger = Union[
    WelcomeTrigger,
    TaskCheckinTrigger,
    MorningBriefTrigger,
    EveningRecapTrigger,
    CoachOpeningTrigger,
]


def synthetic_message_for(trigger: Trigger) -> str:
    """Produces the [SYSTEM] message that REACT sees as 'user content'.
    The persona/REACT prompt knows to treat these as triggers, not user speech.
    """
    if isinstance(trigger, WelcomeTrigger):
        suffix = f" Their first words: '{trigger.initial_message}'." if trigger.initial_message else ""
        return f"[SYSTEM_TRIGGER:welcome] A new user just joined.{suffix}"
    if isinstance(trigger, TaskCheckinTrigger):
        attempt_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(trigger.attempt, f"attempt {trigger.attempt}")
        piggy = ""
        if trigger.piggyback_with:
            piggy = f" Also gently check on '{trigger.piggyback_with.task_title}' from before."
        return (
            f"[SYSTEM_TRIGGER:task_checkin] {attempt_label} check-in for task "
            f"'{trigger.task_title}' (deadline {trigger.deadline}).{piggy}"
        )
    if isinstance(trigger, MorningBriefTrigger):
        head = f" Headline task: {trigger.headline_task}." if trigger.headline_task else ""
        plan = json.dumps(trigger.today_plan, ensure_ascii=False)
        habits = json.dumps(trigger.habits_today, ensure_ascii=False)
        return (
            f"[SYSTEM_TRIGGER:morning_brief] Date {trigger.date}.{head} "
            f"Today's plan: {plan}. Habits: {habits}."
        )
    if isinstance(trigger, EveningRecapTrigger):
        return (
            f"[SYSTEM_TRIGGER:evening_recap] Date {trigger.date}. "
            f"Payload: {trigger.model_dump_json(exclude={'type', 'date'})}"
        )
    if isinstance(trigger, CoachOpeningTrigger):
        return (
            f"[SYSTEM_TRIGGER:coach_opening] Begin a coach session. Reason: {trigger.reason}. "
            f"Open warmly with one question grounded in this signal."
        )
    raise ValueError(f"unknown trigger type: {type(trigger)}")
