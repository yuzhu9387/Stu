from enum import Enum

from pydantic import BaseModel


class Quadrant(str, Enum):
    URGENT_IMPORTANT = "urgent_important"
    IMPORTANT = "important"
    URGENT = "urgent"
    NEITHER = "neither"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskSource(str, Enum):
    MANUAL = "manual"
    LARK_MSG = "lark_msg"
    EMAIL = "email"
    CALENDAR = "calendar"


class SlotType(str, Enum):
    TASK = "task"
    HABIT = "habit"
    CALENDAR_EVENT = "calendar_event"
    BREAK = "break"
    FREE = "free"


class FrequencyType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class ReminderType(str, Enum):
    SCHEDULED = "scheduled"
    SMART = "smart"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DISMISSED = "dismissed"


class ReportType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class DialogueFlowType(str, Enum):
    ONBOARDING = "onboarding"
    ADD_TASK = "add_task"
    ADJUST_PLAN = "adjust_plan"
    SET_GOAL = "set_goal"
    ADD_HABIT = "add_habit"
    REVIEW_PLAN = "review_plan"
    QUICK_QUERY = "quick_query"


class DialogueSessionStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"


class TimestampMixin(BaseModel):
    model_config = {"from_attributes": True}
