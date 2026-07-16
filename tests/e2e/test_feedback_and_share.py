from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.feedback.repository import SqlFeedbackRepository
from recipe_agent.domain.feedback.service import FeedbackService
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
)
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.domain.sharing.projection import ShareProjection
from recipe_agent.domain.sharing.repository import SqlShareRepository
from recipe_agent.domain.sharing.service import ShareService


@pytest.mark.asyncio
async def test_feedback_version_and_private_share_flow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    household_id = uuid4()
    recipes = RecipeRepository(session_factory)
    recipe = await recipes.create(
        household_id,
        RecipeCandidate(
            name="Family Soup",
            ingredients=(RecipeIngredientCandidate(name="tomato"),),
            steps=(RecipeStepCandidate(number=1, text="Simmer."),),
        ),
    )
    feedback = FeedbackService(repository=SqlFeedbackRepository(session_factory))

    outcome = await feedback.record(
        household_id,
        recipe.id,
        "Cook five minutes longer",
    )

    assert outcome.recipe_version.parent_version_id is not None
    projected = ShareProjection().recipe(
        {
            "id": recipe.id,
            "name": recipe.name,
            "ingredients": [item.name for item in recipe.ingredients],
            "steps": [item.text for item in recipe.steps],
            "child_name": "private",
        }
    )
    shares = ShareService(repository=SqlShareRepository(session_factory))
    delivery = await shares.create_snapshot(
        projected.model_dump(mode="json"),
        expires_in=timedelta(hours=1),
    )

    resolved = await shares.resolve_token(delivery.token)
    assert resolved.snapshot["name"] == "Family Soup"
    assert "child_name" not in resolved.snapshot
