"""Persist feedback before applying structural recipe changes."""

from typing import Protocol
from uuid import UUID

from recipe_agent.domain.feedback.contracts import (
    FeedbackEvent,
    FeedbackOutcome,
    RecipeVersionReference,
)


class FeedbackRepository(Protocol):
    async def save_event(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        recipe_id: UUID,
        raw_text: str,
    ) -> FeedbackEvent: ...

    async def active_version_id(self, household_id: UUID, recipe_id: UUID) -> UUID: ...

    async def create_version(
        self, recipe_id: UUID, parent_version_id: UUID, instruction: str
    ) -> RecipeVersionReference: ...


class FeedbackService:
    def __init__(self, *, repository: FeedbackRepository) -> None:
        self._repository = repository

    async def record(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        recipe_id: UUID,
        raw_text: str,
    ) -> FeedbackOutcome:
        event = await self._repository.save_event(
            owner_account_id, household_id, recipe_id, raw_text
        )
        parent_version_id = await self._repository.active_version_id(household_id, recipe_id)
        version = await self._repository.create_version(
            recipe_id,
            parent_version_id,
            raw_text,
        )
        return FeedbackOutcome.model_validate({"feedback_event": event, "recipe_version": version})

    @staticmethod
    def validate_rating(value: int) -> int:
        if not 1 <= value <= 5:
            raise ValueError("Rating must be between one and five")
        return value
