"""Weekly planning and targeted replacement."""

from datetime import date
from typing import Protocol
from uuid import UUID, uuid4

from recipe_agent.domain.planning.contracts import MealPlan, PlanItem, PlanSlot
from recipe_agent.domain.recommendations.contracts import (
    RecommendationQuery,
    RecommendationResult,
)


class PlanRepository(Protocol):
    async def get(self, household_id: UUID, plan_id: UUID) -> MealPlan: ...

    async def save(self, plan: MealPlan) -> MealPlan: ...


class RecommendationProvider(Protocol):
    async def recommend(
        self, query: RecommendationQuery
    ) -> tuple[RecommendationResult, RecommendationResult, RecommendationResult]: ...


class PlanItemNotFoundError(LookupError):
    """The requested plan slot does not exist."""


class PlanningService:
    def __init__(
        self,
        *,
        repository: PlanRepository,
        recommendations: RecommendationProvider,
    ) -> None:
        self._repository = repository
        self._recommendations = recommendations

    async def create_week(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        week_start: date,
        slots: tuple[PlanSlot, ...],
    ) -> MealPlan:
        selected_recipe_ids: set[UUID] = set()
        items: list[PlanItem] = []
        for slot in slots:
            recommendations = await self._recommendations.recommend(
                RecommendationQuery(household_id=household_id)
            )
            selected = next(
                (item for item in recommendations if item.id not in selected_recipe_ids),
                None,
            )
            if selected is None:
                raise PlanItemNotFoundError("No non-duplicate recommendation is available")
            selected_recipe_ids.add(selected.id)
            items.append(
                PlanItem(
                    id=uuid4(),
                    day=slot.day,
                    slot=slot.slot,
                    recipe_id=selected.id,
                    recipe_name=selected.name,
                    reason_codes=selected.reason_codes,
                )
            )
        plan = MealPlan(
            id=uuid4(),
            owner_account_id=owner_account_id,
            household_id=household_id,
            week_start=week_start,
            version=1,
            items=tuple(items),
        )
        return await self._repository.save(plan)

    async def replace_item(
        self,
        household_id: UUID,
        plan_id: UUID,
        day: date,
    ) -> MealPlan:
        updated = await self.preview_replace_item(household_id, plan_id, day)
        return await self._repository.save(updated)

    async def preview_replace_item(
        self,
        household_id: UUID,
        plan_id: UUID,
        day: date,
    ) -> MealPlan:
        """Calculate a replacement without saving the proposed plan."""

        plan = await self._repository.get(household_id, plan_id)
        target = next((item for item in plan.items if item.day == day), None)
        if target is None:
            raise PlanItemNotFoundError("Plan item not found")
        recommendations = await self._recommendations.recommend(
            RecommendationQuery(household_id=household_id)
        )
        preserved_recipe_ids = {item.recipe_id for item in plan.items if item.id != target.id}
        replacement = next(
            (item for item in recommendations if item.id not in preserved_recipe_ids),
            None,
        )
        if replacement is None:
            raise PlanItemNotFoundError("No non-duplicate replacement is available")
        replacement_item = PlanItem(
            id=uuid4(),
            day=target.day,
            slot=target.slot,
            recipe_id=replacement.id,
            recipe_name=replacement.name,
            reason_codes=replacement.reason_codes,
        )
        updated = plan.model_copy(
            update={
                "version": plan.version + 1,
                "items": tuple(
                    replacement_item if item.id == target.id else item for item in plan.items
                ),
            }
        )
        return updated
