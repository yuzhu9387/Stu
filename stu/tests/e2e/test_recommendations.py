from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationFeatures,
    RecommendationQuery,
    RecommendationSource,
)
from recipe_agent.domain.recommendations.service import RecommendationService


def recommendation_candidate(name: str) -> RecommendationCandidate:
    value = Decimal("0.8")
    return RecommendationCandidate(
        id=uuid4(),
        name=name,
        source=RecommendationSource.HOUSEHOLD,
        features=RecommendationFeatures(
            ingredient_match=value,
            meal_type_fit=value,
            age_fit=value,
            rating=value,
            time_fit=value,
            scenario_fit=value,
            diversity=value,
        ),
    )


class ThreeRecipes:
    async def candidates(self, query: RecommendationQuery) -> list[RecommendationCandidate]:
        return [
            recommendation_candidate("Soup"),
            recommendation_candidate("Noodles"),
            recommendation_candidate("Rice"),
        ]


class UnusedGenerator:
    async def generate(
        self, query: RecommendationQuery, count: int
    ) -> list[RecommendationCandidate]:
        raise AssertionError("Generator should not be called")


def test_recommendation_api_returns_exactly_three_for_authenticated_household() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    account_id = uuid4()
    household_id = uuid4()
    app.state.recommendation_service = RecommendationService(
        household=ThreeRecipes(), generator=UnusedGenerator()
    )
    app.dependency_overrides[get_household_scope] = lambda: HouseholdScope(
        account_id=account_id,
        household_id=household_id,
    )

    response = TestClient(app).post(
        "/api/v1/recommendations",
        json={"ingredients": ["tomato"], "age_years": 8},
    )

    assert response.status_code == 200
    assert len(response.json()["recommendations"]) == 3
