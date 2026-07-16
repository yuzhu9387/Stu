"""Raw-first import orchestration."""

from uuid import UUID

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

    async def process(self, raw_input_id: UUID) -> ImportOutcome:
        raw = await self._repository.get_unscoped(raw_input_id)
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
            await self._repository.mark_needs_review(raw.id, str(error))
            raise
        if self._ai_provider is None or self._recipes is None:
            raise RuntimeError("Recipe extraction dependencies are not configured")
        candidate = await self._ai_provider.parse_structured(extracted.text, RecipeCandidate)
        recipe = await self._recipes.create(raw.owner_account_id, raw.household_id, candidate)
        await self._repository.mark_extracted(raw.id)
        return ImportOutcome(
            household_id=raw.household_id,
            raw_input_id=raw.id,
            recipe_id=recipe.id,
            extracted=extracted,
        )
