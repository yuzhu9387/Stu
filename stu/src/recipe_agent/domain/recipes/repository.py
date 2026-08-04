"""Account-scoped raw input and household-scoped recipe persistence."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.conversation.receipts import add_receipt, receipt_result
from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.imports.contracts import ImportCommand, InputKind
from recipe_agent.domain.recipes.contracts import (
    RawInputSummary,
    RecipeCandidate,
    RecipeDetail,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
    RecipeSummary,
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

    async def list_summaries(self, scope: HouseholdScope) -> tuple[RawInputSummary, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RawInput, Account.email)
                .join(Account, Account.id == RawInput.owner_account_id)
                .where(
                    RawInput.owner_account_id == scope.account_id,
                    RawInput.household_id == scope.household_id,
                )
                .order_by(RawInput.created_at.desc(), RawInput.id)
                .limit(100)
            )
            return tuple(self._summary(record, email, scope) for record, email in result.all())

    async def get_summary(self, scope: HouseholdScope, raw_input_id: UUID) -> RawInputSummary:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RawInput, Account.email)
                .join(Account, Account.id == RawInput.owner_account_id)
                .where(
                    RawInput.id == raw_input_id,
                    RawInput.owner_account_id == scope.account_id,
                    RawInput.household_id == scope.household_id,
                )
            )
            row = result.one_or_none()
            if row is None:
                raise RawInputNotFoundError("Raw input not found")
            return self._summary(row[0], row[1], scope)

    @staticmethod
    def _summary(record: RawInput, email: str, scope: HouseholdScope) -> RawInputSummary:
        return RawInputSummary(
            id=record.id,
            owner_account_id=record.owner_account_id,
            owner_display_name=_owner_display_name(email),
            is_owned_by_current_account=record.owner_account_id == scope.account_id,
            household_id=record.household_id,
            kind=record.kind,
            status=(
                record.status.value if isinstance(record.status, RawInputStatus) else record.status
            ),
            error_code=(
                "processing_failed"
                if record.status is RawInputStatus.NEEDS_REVIEW or record.error is not None
                else None
            ),
            created_at=record.created_at,
        )

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
        self,
        owner_account_id: UUID,
        household_id: UUID,
        candidate: RecipeCandidate,
        *,
        source_action_id: UUID | None = None,
        visibility: str = "family",
        meal_type: str = "dinner",
        prep_minutes: int = 0,
        cook_minutes: int = 0,
        suitable_age_years: int = 0,
        image_url: str | None = None,
    ) -> RecipeView:
        async with self._session_factory() as session:
            if source_action_id is not None:
                existing = await receipt_result(session, source_action_id, "save_recipe")
                if existing is not None:
                    return RecipeView.model_validate(existing)
            recipe = Recipe(
                owner_account_id=owner_account_id,
                household_id=household_id,
                visibility=visibility,
                meal_type=meal_type,
                prep_minutes=prep_minutes,
                cook_minutes=cook_minutes,
                suitable_age_years=suitable_age_years,
                image_url=image_url,
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
            view = RecipeView(
                id=recipe.id,
                household_id=household_id,
                name=candidate.name,
                ingredients=candidate.ingredients,
                steps=candidate.steps,
            )
            if source_action_id is not None:
                add_receipt(session, source_action_id, "save_recipe", view)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if source_action_id is None:
                    raise
                completed = await receipt_result(session, source_action_id, "save_recipe")
                if completed is None:
                    raise
                return RecipeView.model_validate(completed)
            return view

    async def update_for_owner(
        self,
        scope: HouseholdScope,
        recipe_id: UUID,
        candidate: RecipeCandidate,
        *,
        visibility: str,
        meal_type: str,
        prep_minutes: int,
        cook_minutes: int,
        suitable_age_years: int,
        image_url: str | None,
    ) -> RecipeDetail:
        async with self._session_factory() as session:
            recipe = await session.scalar(
                select(Recipe).where(
                    Recipe.id == recipe_id,
                    Recipe.owner_account_id == scope.account_id,
                    Recipe.household_id == scope.household_id,
                )
            )
            if recipe is None or recipe.active_version_id is None:
                raise RecipeNotFoundError("Recipe not found")
            previous_version_id = recipe.active_version_id
            version = RecipeVersion(
                recipe_id=recipe.id,
                parent_version_id=previous_version_id,
                name=candidate.name,
            )
            session.add(version)
            await session.flush()
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
            recipe.active_version_id = version.id
            recipe.visibility = visibility
            recipe.meal_type = meal_type
            recipe.prep_minutes = prep_minutes
            recipe.cook_minutes = cook_minutes
            recipe.suitable_age_years = suitable_age_years
            recipe.image_url = image_url
            recipe.updated_at = datetime.now(UTC)
            await session.commit()
        return await self.get_for_scope(scope, recipe_id)

    async def delete_for_owner(self, scope: HouseholdScope, recipe_id: UUID) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(Recipe).where(
                    Recipe.id == recipe_id,
                    Recipe.owner_account_id == scope.account_id,
                    Recipe.household_id == scope.household_id,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise RecipeNotFoundError("Recipe not found")
            await session.commit()

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

    async def search_owned(self, scope: HouseholdScope, query: str) -> tuple[RecipeSummary, ...]:
        return await self._search(scope, query, owned_only=True)

    async def search_family(self, scope: HouseholdScope, query: str) -> tuple[RecipeSummary, ...]:
        return await self._search(scope, query, owned_only=False)

    async def list_for_scope(self, scope: HouseholdScope) -> tuple[RecipeSummary, ...]:
        return await self._search(scope, "", owned_only=False)

    async def _search(
        self, scope: HouseholdScope, query: str, *, owned_only: bool
    ) -> tuple[RecipeSummary, ...]:
        async with self._session_factory() as session:
            statement = (
                select(Recipe, RecipeVersion.name, Account.email)
                .join(RecipeVersion, RecipeVersion.id == Recipe.active_version_id)
                .join(Account, Account.id == Recipe.owner_account_id)
                .where(Recipe.household_id == scope.household_id)
            )
            if owned_only:
                statement = statement.where(Recipe.owner_account_id == scope.account_id)
            else:
                statement = statement.where(
                    or_(
                        Recipe.visibility == "family",
                        Recipe.owner_account_id == scope.account_id,
                    )
                )
            normalized_query = query.strip()
            if normalized_query:
                statement = statement.where(
                    RecipeVersion.name.icontains(normalized_query, autoescape=True)
                )
            result = await session.execute(
                statement.order_by(Recipe.created_at.desc(), Recipe.id).limit(100)
            )
            return tuple(
                self._summary(record, name, email, scope) for record, name, email in result.all()
            )

    async def get_for_scope(self, scope: HouseholdScope, recipe_id: UUID) -> RecipeDetail:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Recipe, RecipeVersion, Account.email)
                .join(RecipeVersion, RecipeVersion.id == Recipe.active_version_id)
                .join(Account, Account.id == Recipe.owner_account_id)
                .where(
                    Recipe.id == recipe_id,
                    Recipe.household_id == scope.household_id,
                    or_(
                        Recipe.visibility == "family",
                        Recipe.owner_account_id == scope.account_id,
                    ),
                )
            )
            row = result.one_or_none()
            if row is None:
                raise RecipeNotFoundError("Recipe not found")
            recipe, version, email = row
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
            return RecipeDetail(
                **self._summary(recipe, version.name, email, scope).model_dump(),
                ingredients=tuple(
                    RecipeIngredientCandidate(
                        name=item.name, quantity=item.quantity, unit=item.unit
                    )
                    for item in ingredient_result.scalars()
                ),
                steps=tuple(
                    RecipeStepCandidate(number=item.number, text=item.text)
                    for item in step_result.scalars()
                ),
            )

    @staticmethod
    def _summary(record: Recipe, name: str, email: str, scope: HouseholdScope) -> RecipeSummary:
        return RecipeSummary(
            id=record.id,
            owner_account_id=record.owner_account_id,
            owner_display_name=_owner_display_name(email),
            is_owned_by_current_account=record.owner_account_id == scope.account_id,
            household_id=record.household_id,
            name=name,
            visibility=record.visibility,
            meal_type=record.meal_type,
            prep_minutes=record.prep_minutes,
            cook_minutes=record.cook_minutes,
            suitable_age_years=record.suitable_age_years,
            image_url=record.image_url,
            created_at=record.created_at,
        )


def _owner_display_name(email: str) -> str:
    return email.partition("@")[0]
