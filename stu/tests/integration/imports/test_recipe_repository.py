from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
)
from recipe_agent.domain.recipes.models import Recipe
from recipe_agent.domain.recipes.repository import RecipeNotFoundError, RecipeRepository


def soup_candidate() -> RecipeCandidate:
    return RecipeCandidate(
        name="Tomato Soup",
        ingredients=(RecipeIngredientCandidate(name="tomato", quantity="3", unit="piece"),),
        steps=(RecipeStepCandidate(number=1, text="Simmer the tomatoes."),),
    )


@pytest.mark.asyncio
async def test_recipe_repository_persists_normalized_candidate_and_scopes_reads(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    household_id = uuid4()
    owner_account_id = uuid4()
    other_household_id = uuid4()
    repository = RecipeRepository(session_factory)

    created = await repository.create(owner_account_id, household_id, soup_candidate())
    loaded = await repository.get(household_id, created.id)
    async with session_factory() as session:
        stored = await session.get(Recipe, created.id)

    assert loaded.name == "Tomato Soup"
    assert stored is not None
    assert stored.owner_account_id == owner_account_id
    assert loaded.ingredients[0].name == "tomato"
    assert loaded.steps[0].number == 1
    with pytest.raises(RecipeNotFoundError):
        await repository.get(other_household_id, created.id)
