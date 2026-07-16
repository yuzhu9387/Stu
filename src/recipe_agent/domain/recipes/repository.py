"""Account-scoped raw input and household-scoped recipe persistence."""

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.imports.contracts import ImportCommand, InputKind
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
    RecipeView,
)
from recipe_agent.domain.recipes.models import (
    RawInput,
    RawInputStatus,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeVersion,
)


class RawInputNotFoundError(LookupError):
    pass


class RecipeNotFoundError(LookupError):
    pass


class EventOutbox(Protocol):
    async def add(
        self,
        session: AsyncSession,
        topic: str,
        payload: Mapping[str, Any],
    ) -> object: ...


class RawInputRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, command: ImportCommand) -> RawInput:
        raw = RawInput(
            owner_account_id=command.owner_account_id,
            household_id=command.household_id,
            kind=command.kind.value,
            source_url=command.source if command.kind is InputKind.URL else None,
            raw_text=command.source if command.kind is InputKind.TEXT else None,
            object_key=command.object_key,
        )
        async with self._session_factory() as session:
            session.add(raw)
            await session.commit()
        return raw

    async def get(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        raw_input_id: UUID,
    ) -> RawInput:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RawInput).where(
                    RawInput.id == raw_input_id,
                    RawInput.owner_account_id == owner_account_id,
                    RawInput.household_id == household_id,
                )
            )
            raw = result.scalar_one_or_none()
            if raw is None:
                raise RawInputNotFoundError("Raw input not found")
            return raw

    async def mark_needs_review(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        raw_input_id: UUID,
        error: str,
    ) -> None:
        await self._set_status(
            owner_account_id,
            household_id,
            raw_input_id,
            RawInputStatus.NEEDS_REVIEW,
            error,
        )

    async def mark_extracted(
        self, owner_account_id: UUID, household_id: UUID, raw_input_id: UUID
    ) -> None:
        await self._set_status(
            owner_account_id,
            household_id,
            raw_input_id,
            RawInputStatus.EXTRACTED,
            None,
        )

    async def _set_status(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        raw_input_id: UUID,
        status: RawInputStatus,
        error: str | None,
    ) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RawInput).where(
                    RawInput.id == raw_input_id,
                    RawInput.owner_account_id == owner_account_id,
                    RawInput.household_id == household_id,
                )
            )
            raw = result.scalar_one_or_none()
            if raw is None:
                raise RawInputNotFoundError("Raw input not found")
            raw.status = status
            raw.error = error
            await session.commit()


class RecipeRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        outbox: EventOutbox | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox

    async def create(
        self, owner_account_id: UUID, household_id: UUID, candidate: RecipeCandidate
    ) -> RecipeView:
        async with self._session_factory() as session:
            recipe = Recipe(
                owner_account_id=owner_account_id,
                household_id=household_id,
            )
            session.add(recipe)
            await session.flush()
            version = RecipeVersion(recipe_id=recipe.id, name=candidate.name)
            session.add(version)
            await session.flush()
            recipe.active_version_id = version.id
            session.add_all(
                [
                    RecipeIngredient(
                        version_id=version.id,
                        position=position,
                        name=ingredient.name,
                        quantity=ingredient.quantity,
                        unit=ingredient.unit,
                    )
                    for position, ingredient in enumerate(candidate.ingredients, start=1)
                ]
            )
            session.add_all(
                [
                    RecipeStep(version_id=version.id, number=step.number, text=step.text)
                    for step in candidate.steps
                ]
            )
            if self._outbox is not None:
                await self._outbox.add(
                    session,
                    "recipe.saved",
                    {"household_id": str(household_id), "recipe_id": str(recipe.id)},
                )
            await session.commit()
            return RecipeView(
                id=recipe.id,
                household_id=household_id,
                name=candidate.name,
                ingredients=candidate.ingredients,
                steps=candidate.steps,
            )

    async def get(self, household_id: UUID, recipe_id: UUID) -> RecipeView:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Recipe).where(
                    Recipe.id == recipe_id,
                    Recipe.household_id == household_id,
                )
            )
            recipe = result.scalar_one_or_none()
            if recipe is None or recipe.active_version_id is None:
                raise RecipeNotFoundError("Recipe not found")
            version = await session.get(RecipeVersion, recipe.active_version_id)
            if version is None:
                raise RecipeNotFoundError("Recipe version not found")
            ingredient_result = await session.execute(
                select(RecipeIngredient)
                .where(RecipeIngredient.version_id == version.id)
                .order_by(RecipeIngredient.position)
            )
            step_result = await session.execute(
                select(RecipeStep)
                .where(RecipeStep.version_id == version.id)
                .order_by(RecipeStep.number)
            )
            return RecipeView(
                id=recipe.id,
                household_id=recipe.household_id,
                name=version.name,
                ingredients=tuple(
                    RecipeIngredientCandidate(
                        name=item.name,
                        quantity=item.quantity,
                        unit=item.unit,
                    )
                    for item in ingredient_result.scalars()
                ),
                steps=tuple(
                    RecipeStepCandidate(number=item.number, text=item.text)
                    for item in step_result.scalars()
                ),
            )
