"""SQL feedback repository and immutable recipe version cloning."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.feedback.contracts import FeedbackEvent, RecipeVersionReference
from recipe_agent.domain.feedback.models import FeedbackEventRecord, RecipeVersionDeltaRecord
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.recipes.models import (
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeVersion,
)


class FeedbackRecipeNotFoundError(LookupError):
    pass


class SqlFeedbackRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_event(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        recipe_id: UUID,
        raw_text: str,
    ) -> FeedbackEvent:
        async with self._session_factory() as session:
            await self._scoped_recipe(session, household_id, recipe_id)
            record = FeedbackEventRecord(
                owner_account_id=owner_account_id,
                household_id=household_id,
                recipe_id=recipe_id,
                raw_text=raw_text,
            )
            session.add(record)
            await session.commit()
            return FeedbackEvent(
                id=record.id,
                owner_account_id=record.owner_account_id,
                household_id=record.household_id,
                recipe_id=record.recipe_id,
                raw_text=record.raw_text,
            )

    async def list_events(self, scope: HouseholdScope) -> tuple[FeedbackEvent, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(FeedbackEventRecord)
                .where(
                    FeedbackEventRecord.owner_account_id == scope.account_id,
                    FeedbackEventRecord.household_id == scope.household_id,
                )
                .order_by(FeedbackEventRecord.created_at.desc(), FeedbackEventRecord.id)
                .limit(100)
            )
            return tuple(
                FeedbackEvent(
                    id=record.id,
                    owner_account_id=record.owner_account_id,
                    household_id=record.household_id,
                    recipe_id=record.recipe_id,
                    raw_text=record.raw_text,
                )
                for record in result.scalars()
            )

    async def active_version_id(self, household_id: UUID, recipe_id: UUID) -> UUID:
        async with self._session_factory() as session:
            recipe = await self._scoped_recipe(session, household_id, recipe_id)
            if recipe.active_version_id is None:
                raise FeedbackRecipeNotFoundError("Active recipe version not found")
            return recipe.active_version_id

    async def create_version(
        self,
        recipe_id: UUID,
        parent_version_id: UUID,
        instruction: str,
    ) -> RecipeVersionReference:
        async with self._session_factory() as session:
            recipe = await session.get(Recipe, recipe_id)
            parent = await session.get(RecipeVersion, parent_version_id)
            if recipe is None or parent is None or parent.recipe_id != recipe_id:
                raise FeedbackRecipeNotFoundError("Recipe version not found")
            version = RecipeVersion(
                recipe_id=recipe_id,
                parent_version_id=parent_version_id,
                name=parent.name,
            )
            session.add(version)
            await session.flush()
            await self._clone_content(session, parent_version_id, version.id)
            session.add(RecipeVersionDeltaRecord(version_id=version.id, instruction=instruction))
            recipe.active_version_id = version.id
            await session.commit()
            return RecipeVersionReference(
                id=version.id,
                recipe_id=recipe_id,
                parent_version_id=parent_version_id,
            )

    @staticmethod
    async def _clone_content(
        session: AsyncSession, parent_version_id: UUID, version_id: UUID
    ) -> None:
        ingredient_result = await session.execute(
            select(RecipeIngredient).where(RecipeIngredient.version_id == parent_version_id)
        )
        step_result = await session.execute(
            select(RecipeStep).where(RecipeStep.version_id == parent_version_id)
        )
        session.add_all(
            [
                RecipeIngredient(
                    version_id=version_id,
                    position=item.position,
                    name=item.name,
                    quantity=item.quantity,
                    unit=item.unit,
                )
                for item in ingredient_result.scalars()
            ]
        )
        session.add_all(
            [
                RecipeStep(
                    version_id=version_id,
                    number=item.number,
                    text=item.text,
                )
                for item in step_result.scalars()
            ]
        )

    @staticmethod
    async def _scoped_recipe(session: AsyncSession, household_id: UUID, recipe_id: UUID) -> Recipe:
        result = await session.execute(
            select(Recipe).where(
                Recipe.id == recipe_id,
                Recipe.household_id == household_id,
            )
        )
        recipe = result.scalar_one_or_none()
        if recipe is None:
            raise FeedbackRecipeNotFoundError("Recipe not found")
        return recipe
