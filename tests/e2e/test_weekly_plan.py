from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.planning.contracts import PlanSlot
from recipe_agent.domain.planning.repository import SqlPlanRepository
from recipe_agent.domain.planning.service import PlanningService
from recipe_agent.domain.recommendations.contracts import (
    RecommendationQuery,
    RecommendationResult,
    RecommendationSource,
)


class RotatingRecommendations:
    async def recommend(
        self, query: RecommendationQuery
    ) -> tuple[RecommendationResult, RecommendationResult, RecommendationResult]:
        items = tuple(
            RecommendationResult(
                id=uuid4(),
                name=f"Meal {index}",
                source=RecommendationSource.HOUSEHOLD,
                score=Decimal("0.8"),
                reason_codes=("from_household_library",),
            )
            for index in range(3)
        )
        return items[0], items[1], items[2]


@pytest.mark.asyncio
async def test_weekly_plan_round_trips_through_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_account_id = uuid4()
    household_id = uuid4()
    monday = date(2026, 7, 13)
    repository = SqlPlanRepository(session_factory)
    service = PlanningService(
        repository=repository,
        recommendations=RotatingRecommendations(),
    )

    created = await service.create_week(
        owner_account_id,
        household_id,
        monday,
        tuple(PlanSlot(day=monday + timedelta(days=offset), slot="dinner") for offset in range(7)),
    )
    loaded = await repository.get(household_id, created.id)

    assert loaded.version == 1
    assert loaded.owner_account_id == owner_account_id
    assert len(loaded.items) == 7
    assert loaded.items[0].day == monday
