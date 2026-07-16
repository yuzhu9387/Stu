"""Feedback events and recipe version references."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FeedbackEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    household_id: UUID
    recipe_id: UUID
    raw_text: str


class RecipeVersionReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    recipe_id: UUID
    parent_version_id: UUID


class FeedbackOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    feedback_event: FeedbackEvent
    recipe_version: RecipeVersionReference
