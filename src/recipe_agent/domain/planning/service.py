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

    async def save(self, plan: MealPlan, *, source_action_id: UUID | None = None) -> MealPlan: ...

    async def get_action_result(self, action_id: UUID, action_type: str) -> MealPlan | None: ...


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
        *,
        source_action_id: UUID | None = None,
        title: str = "Weekly plan",
        generated_by_ai: bool = False,
        preferences: tuple[str, ...] = (),
        people_count: int = 2,
        notes: str | None = None,
    ) -> MealPlan:
        if source_action_id is not None:
            completed = await self._repository.get_action_result(source_action_id, "create_plan")
            if completed is not None:
                return completed
        recommendations_by_slot: dict[
            str, tuple[RecommendationResult, RecommendationResult, RecommendationResult]
        ] = {}
        slot_usage: dict[str, int] = {}
        items: list[PlanItem] = []
        for slot in slots:
            if slot.slot not in recommendations_by_slot:
                recommendations_by_slot[slot.slot] = await self._recommendations.recommend(
                    RecommendationQuery(
                        household_id=household_id,
                        meal_type=slot.slot,
                        preferences=preferences,
                        people_count=people_count,
                        notes=notes,
                    )
                )
            recommendations = recommendations_by_slot[slot.slot]
            usage = slot_usage.get(slot.slot, 0)
            selected = recommendations[usage % len(recommendations)]
            slot_usage[slot.slot] = usage + 1
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
            title=title,
            generated_by_ai=generated_by_ai,
            week_start=week_start,
            version=1,
            items=tuple(items),
        )
        if source_action_id is None:
            return await self._repository.save(plan)
        return await self._repository.save(plan, source_action_id=source_action_id)

    async def replace_item(
        self,
        household_id: UUID,
        plan_id: UUID,
        day: date,
        *,
        source_action_id: UUID | None = None,
    ) -> MealPlan:
        if source_action_id is not None:
            completed = await self._repository.get_action_result(
                source_action_id, "replace_plan_item"
            )
            if completed is not None:
                return completed
        plan = await self._repository.get(household_id, plan_id)
        updated = await self.preview_replace_item(plan, day)
        if source_action_id is None:
            return await self._repository.save(updated)
        return await self._repository.save(updated, source_action_id=source_action_id)

    async def preview_replace_item(
        self,
        plan: MealPlan,
        day: date,
    ) -> MealPlan:
        """Calculate a replacement without saving the proposed plan."""

        target = next((item for item in plan.items if item.day == day), None)
        if target is None:
            raise PlanItemNotFoundError("Plan item not found")
        recommendations = await self._recommendations.recommend(
            RecommendationQuery(household_id=plan.household_id)
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
