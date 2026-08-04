from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Profile(BaseModel):
    name: Optional[str] = None
    diet: Optional[str] = None
    timezone: Optional[str] = None
    wake_up: Optional[str] = None
    work_start: Optional[str] = None
    peak_hours_start: Optional[str] = None
    peak_hours_end: Optional[str] = None
    work_end: Optional[str] = None
    sleep_time: Optional[str] = None
    reminder_minutes_before: Optional[int] = None
    weekend_plans: Optional[bool] = None
    yearly_goals: Optional[str] = None
    daily_habits: Optional[str] = None


class Pattern(BaseModel):
    pattern: str
    confidence: float = 0.5
    learned_at: Optional[str] = None
    last_reinforced_at: Optional[str] = None


OnboardingStatus = Literal["pending", "in_progress", "completed"]


class UserPreferences(BaseModel):
    profile: Profile = Field(default_factory=Profile)
    procedural: list[Pattern] = Field(default_factory=list)
    onboarding_status: OnboardingStatus = "pending"

    @classmethod
    def from_jsonb(cls, raw: Optional[dict]) -> "UserPreferences":
        if not raw:
            return cls()
        return cls.model_validate(raw)
