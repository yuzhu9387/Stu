from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from recipe_agent.domain.planning.contracts import MealPlan, PlanItem, PlanSlot
from recipe_agent.domain.planning.service import PlanningService
from recipe_agent.domain.recommendations.contracts import (
    RecommendationQuery,
    RecommendationResult,
    RecommendationSource,
)


class MemoryPlanRepository:
    def __init__(self, plan: MealPlan) -> None:
        self.plan = plan

    async def get(self, household_id: object, plan_id: object) -> MealPlan:
        return self.plan

    async def save(self, plan: MealPlan) -> MealPlan:
        self.plan = plan
        return plan


class FixedRecommendations:
    def __init__(self, recipe_id: object) -> None:
        self.recipe_id = recipe_id

    async def recommend(
        self, query: RecommendationQuery
    ) -> tuple[RecommendationResult, RecommendationResult, RecommendationResult]:
        results = tuple(
            RecommendationResult(
                id=self.recipe_id if index == 0 else uuid4(),
                name=f"Replacement {index}",
                source=RecommendationSource.HOUSEHOLD,
                score=Decimal("0.8"),
                reason_codes=("ingredient_match",),
            )
            for index in range(3)
        )
        return results[0], results[1], results[2]


@pytest.mark.asyncio
async def test_replacing_one_item_preserves_other_plan_items() -> None:
    household_id = uuid4()
    monday = date(2026, 7, 13)
    items = tuple(
        PlanItem(
            id=uuid4(),
            day=monday + timedelta(days=offset),
            slot="dinner",
            recipe_id=uuid4(),
            recipe_name=f"Meal {offset}",
            reason_codes=("from_household_library",),
        )
        for offset in range(3)
    )
    saved_plan = MealPlan(
        id=uuid4(),
        household_id=household_id,
        week_start=monday,
        version=1,
        items=items,
    )
    repository = MemoryPlanRepository(saved_plan)
    service = PlanningService(
        repository=repository,
        recommendations=FixedRecommendations(uuid4()),
    )
    target_day = monday + timedelta(days=1)
    original_ids = {item.id for item in saved_plan.items if item.day != target_day}

    updated = await service.replace_item(household_id, saved_plan.id, target_day)

    assert original_ids <= {item.id for item in updated.items}
    assert updated.version == 2
    assert next(item for item in updated.items if item.day == target_day).id not in {
        item.id for item in saved_plan.items
    }


@pytest.mark.asyncio
async def test_create_week_avoids_duplicate_recipe_ids() -> None:
    household_id = uuid4()
    monday = date(2026, 7, 13)
    empty = MealPlan(
        id=uuid4(),
        household_id=household_id,
        week_start=monday,
        version=1,
        items=(),
    )
    repository = MemoryPlanRepository(empty)
    service = PlanningService(
        repository=repository,
        recommendations=FixedRecommendations(uuid4()),
    )

    plan = await service.create_week(
        household_id,
        monday,
        tuple(PlanSlot(day=monday + timedelta(days=offset), slot="dinner") for offset in range(3)),
    )

    assert len(plan.items) == 3
    assert len({item.recipe_id for item in plan.items}) == 3
