from decimal import Decimal
from uuid import uuid4

import pytest

from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationFeatures,
    RecommendationQuery,
    RecommendationSource,
)
from recipe_agent.domain.recommendations.service import (
    RecommendationCapacityError,
    RecommendationService,
)


def candidate(
    name: str,
    source: RecommendationSource,
    *,
    allergens: frozenset[str] = frozenset(),
) -> RecommendationCandidate:
    features = RecommendationFeatures(
        ingredient_match=Decimal("0.8"),
        meal_type_fit=Decimal("0.8"),
        age_fit=Decimal("0.8"),
        rating=Decimal("0.8"),
        time_fit=Decimal("0.8"),
        scenario_fit=Decimal("0.8"),
        diversity=Decimal("0.8"),
    )
    return RecommendationCandidate(
        id=uuid4(),
        name=name,
        source=source,
        features=features,
        allergens=allergens,
    )


class FixedHouseholdSource:
    def __init__(self, items: list[RecommendationCandidate]) -> None:
        self.items = items

    async def candidates(self, query: RecommendationQuery) -> list[RecommendationCandidate]:
        return self.items


class RecordingGenerator:
    def __init__(self, items: list[RecommendationCandidate]) -> None:
        self.items = items
        self.requested_counts: list[int] = []

    async def generate(
        self, query: RecommendationQuery, count: int
    ) -> list[RecommendationCandidate]:
        self.requested_counts.append(count)
        return self.items[:count]


@pytest.mark.asyncio
async def test_recommendation_returns_exactly_three_household_first() -> None:
    household = FixedHouseholdSource(
        [
            candidate("Soup", RecommendationSource.HOUSEHOLD),
            candidate("Noodles", RecommendationSource.HOUSEHOLD),
        ]
    )
    generator = RecordingGenerator([candidate("Risotto", RecommendationSource.GENERATED)])
    service = RecommendationService(household=household, generator=generator)

    results = await service.recommend(RecommendationQuery(household_id=uuid4(), age_years=8))

    assert len(results) == 3
    assert [result.source for result in results] == [
        RecommendationSource.HOUSEHOLD,
        RecommendationSource.HOUSEHOLD,
        RecommendationSource.GENERATED,
    ]
    assert generator.requested_counts == [1]


@pytest.mark.asyncio
async def test_unsafe_generated_shortfall_raises_capacity_error() -> None:
    generator = RecordingGenerator(
        [
            candidate(
                "Peanut noodles",
                RecommendationSource.GENERATED,
                allergens=frozenset({"peanut"}),
            )
        ]
    )
    service = RecommendationService(household=FixedHouseholdSource([]), generator=generator)
    query = RecommendationQuery(
        household_id=uuid4(),
        allergies=frozenset({"peanut"}),
        age_years=8,
    )

    with pytest.raises(RecommendationCapacityError):
        await service.recommend(query)
