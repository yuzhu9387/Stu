from uuid import uuid4

import pytest

from recipe_agent.domain.feedback.contracts import FeedbackEvent, RecipeVersionReference
from recipe_agent.domain.feedback.service import FeedbackService


class RecordingFeedbackRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def save_event(self, household_id: object, recipe_id: object, raw_text: str):
        self.calls.append("event")
        return FeedbackEvent(
            id=uuid4(),
            household_id=household_id,
            recipe_id=recipe_id,
            raw_text=raw_text,
        )

    async def active_version_id(self, household_id: object, recipe_id: object):
        return uuid4()

    async def create_version(self, recipe_id: object, parent_version_id: object, instruction: str):
        self.calls.append("version")
        return RecipeVersionReference(
            id=uuid4(),
            recipe_id=recipe_id,
            parent_version_id=parent_version_id,
        )


@pytest.mark.asyncio
async def test_structural_feedback_creates_event_before_new_version() -> None:
    repository = RecordingFeedbackRepository()
    service = FeedbackService(repository=repository)
    household_id = uuid4()
    recipe_id = uuid4()

    outcome = await service.record(household_id, recipe_id, "Cook five minutes longer")

    assert outcome.feedback_event.raw_text == "Cook five minutes longer"
    assert outcome.recipe_version.parent_version_id is not None
    assert repository.calls == ["event", "version"]


def test_rating_rejects_values_outside_one_to_five() -> None:
    with pytest.raises(ValueError):
        FeedbackService.validate_rating(6)
