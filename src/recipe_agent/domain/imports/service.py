"""Raw-first import orchestration."""

from uuid import UUID, uuid4

from recipe_agent.domain.common.ai import AIProvider
from recipe_agent.domain.imports.adapters import AdapterRegistry
from recipe_agent.domain.imports.contracts import (
    ImportCommand,
    ImportOutcome,
    ImportReceipt,
    InputKind,
)
from recipe_agent.domain.recipes.contracts import RecipeCandidate
from recipe_agent.domain.recipes.repository import RawInputRepository, RecipeRepository


class ImportService:
    def __init__(
        self,
        *,
        repository: RawInputRepository,
        adapters: AdapterRegistry,
        ai_provider: AIProvider | None = None,
        recipes: RecipeRepository | None = None,
    ) -> None:
        self._repository = repository
        self._adapters = adapters
        self._ai_provider = ai_provider
        self._recipes = recipes

    async def receive(self, command: ImportCommand) -> ImportReceipt:
        raw = await self._repository.create(command)
        return ImportReceipt(household_id=raw.household_id, raw_input_id=raw.id)

    async def process(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        raw_input_id: UUID,
    ) -> ImportOutcome:
        raw = await self._repository.get(owner_account_id, household_id, raw_input_id)
        command = ImportCommand(
            owner_account_id=raw.owner_account_id,
            household_id=raw.household_id,
            kind=InputKind(raw.kind),
            source=raw.source_url or raw.raw_text or raw.object_key or "missing source",
            object_key=raw.object_key,
        )
        try:
            extracted = await self._adapters.extract(raw.id, command)
        except Exception as error:
            await self._repository.mark_needs_review(
                owner_account_id,
                household_id,
                raw.id,
                str(error),
            )
            raise
        if self._ai_provider is None or self._recipes is None:
            raise RuntimeError("Recipe extraction dependencies are not configured")
        candidate = await self._ai_provider.parse_structured(extracted.text, RecipeCandidate)
        recipe = await self._recipes.create(raw.owner_account_id, raw.household_id, candidate)
        await self._repository.mark_extracted(owner_account_id, household_id, raw.id)
        return ImportOutcome(
            household_id=raw.household_id,
            raw_input_id=raw.id,
            recipe_id=recipe.id,
            extracted=extracted,
        )

    async def preview(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        kind: InputKind,
        source: str,
    ) -> RecipeCandidate:
        """Extract and parse a recipe without persisting raw input or a recipe."""

        if self._ai_provider is None:
            raise RuntimeError("Recipe extraction dependencies are not configured")
        command = ImportCommand(
            owner_account_id=owner_account_id,
            household_id=household_id,
            kind=kind,
            source=source,
        )
        extracted = await self._adapters.extract(uuid4(), command)
        return await self._ai_provider.parse_structured(extracted.text, RecipeCandidate)
