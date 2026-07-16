from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.imports.adapters import AdapterRegistry, ExternalPlatformError, TextAdapter
from recipe_agent.domain.imports.contracts import ExtractedInput, ImportCommand, InputKind
from recipe_agent.domain.imports.service import ImportService
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
)
from recipe_agent.domain.recipes.models import RawInputStatus
from recipe_agent.domain.recipes.repository import (
    RawInputNotFoundError,
    RawInputRepository,
    RecipeRepository,
)


class FailingAdapter:
    def supports(self, command: ImportCommand) -> bool:
        return True

    async def extract(self, raw_input_id: object, command: ImportCommand) -> ExtractedInput:
        raise ExternalPlatformError("source unavailable")


@pytest.mark.asyncio
async def test_raw_input_survives_adapter_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = RawInputRepository(session_factory)
    service = ImportService(repository=repository, adapters=AdapterRegistry([FailingAdapter()]))
    command = ImportCommand(
        owner_account_id=uuid4(),
        household_id=uuid4(),
        kind=InputKind.URL,
        source="https://example.invalid/recipe",
    )

    receipt = await service.receive(command)
    with pytest.raises(ExternalPlatformError):
        await service.process(
            command.owner_account_id,
            command.household_id,
            receipt.raw_input_id,
        )

    saved = await repository.get(
        command.owner_account_id,
        receipt.household_id,
        receipt.raw_input_id,
    )
    assert saved.status is RawInputStatus.NEEDS_REVIEW
    assert saved.owner_account_id == command.owner_account_id
    assert saved.source_url == "https://example.invalid/recipe"


@pytest.mark.asyncio
async def test_raw_input_is_private_between_accounts_in_one_family(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = RawInputRepository(session_factory)
    owner_account_id = uuid4()
    other_account_id = uuid4()
    household_id = uuid4()
    raw = await repository.create(
        ImportCommand(
            owner_account_id=owner_account_id,
            household_id=household_id,
            kind=InputKind.TEXT,
            source="private family note",
        )
    )

    with pytest.raises(RawInputNotFoundError):
        await repository.get(other_account_id, household_id, raw.id)

    owned_raw = await repository.get(owner_account_id, household_id, raw.id)
    assert owned_raw.id == raw.id
    assert owned_raw.owner_account_id == owner_account_id


class FixedAIProvider:
    async def parse_structured(self, prompt: str, schema: object) -> RecipeCandidate:
        return RecipeCandidate(
            name="Family Soup",
            ingredients=(RecipeIngredientCandidate(name="water", quantity="1", unit="liter"),),
            steps=(RecipeStepCandidate(number=1, text="Boil."),),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]


@pytest.mark.asyncio
async def test_successful_import_persists_structured_recipe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw_repository = RawInputRepository(session_factory)
    recipe_repository = RecipeRepository(session_factory)
    service = ImportService(
        repository=raw_repository,
        adapters=AdapterRegistry([TextAdapter()]),
        ai_provider=FixedAIProvider(),
        recipes=recipe_repository,
    )
    command = ImportCommand(
        owner_account_id=uuid4(),
        household_id=uuid4(),
        kind=InputKind.TEXT,
        source="Family soup: boil one liter of water.",
    )

    receipt = await service.receive(command)
    outcome = await service.process(
        command.owner_account_id,
        command.household_id,
        receipt.raw_input_id,
    )
    recipe = await recipe_repository.get(command.household_id, outcome.recipe_id)
    saved_raw = await raw_repository.get(
        command.owner_account_id,
        command.household_id,
        receipt.raw_input_id,
    )

    assert recipe.name == "Family Soup"
    assert saved_raw.owner_account_id == command.owner_account_id
    assert saved_raw.status is RawInputStatus.EXTRACTED
