from uuid import uuid4

import pytest
from pydantic import ValidationError

from recipe_agent.domain.imports.adapters import (
    AdapterRegistry,
    ExternalPlatformError,
    GenericURLAdapter,
    XiaohongshuURLAdapter,
)
from recipe_agent.domain.imports.contracts import ExtractedInput, ImportCommand, InputKind
from recipe_agent.domain.recipes.contracts import RecipeCandidate, RecipeStepCandidate


def test_xiaohongshu_adapter_wins_before_generic_url() -> None:
    registry = AdapterRegistry([GenericURLAdapter(), XiaohongshuURLAdapter()])
    command = ImportCommand(
        owner_account_id=uuid4(),
        household_id=uuid4(),
        kind=InputKind.URL,
        source="https://www.xiaohongshu.com/explore/recipe",
    )

    assert isinstance(registry.resolve(command), XiaohongshuURLAdapter)


def test_recipe_candidate_rejects_steps_without_ingredients() -> None:
    with pytest.raises(ValidationError):
        RecipeCandidate(
            name="Soup",
            ingredients=(),
            steps=(RecipeStepCandidate(number=1, text="Boil"),),
        )


class FailingPrimaryAdapter:
    priority = 100

    def supports(self, command: ImportCommand) -> bool:
        return True

    async def extract(self, raw_input_id: object, command: ImportCommand) -> ExtractedInput:
        raise ExternalPlatformError("blocked")


class SuccessfulFallbackAdapter:
    priority = 10

    def supports(self, command: ImportCommand) -> bool:
        return True

    async def extract(self, raw_input_id: object, command: ImportCommand) -> ExtractedInput:
        return ExtractedInput(text="fallback recipe")


@pytest.mark.asyncio
async def test_registry_falls_back_after_external_platform_failure() -> None:
    registry = AdapterRegistry([SuccessfulFallbackAdapter(), FailingPrimaryAdapter()])
    command = ImportCommand(
        owner_account_id=uuid4(),
        household_id=uuid4(),
        kind=InputKind.URL,
        source="https://x.test",
    )

    extracted = await registry.extract(uuid4(), command)

    assert extracted.text == "fallback recipe"
