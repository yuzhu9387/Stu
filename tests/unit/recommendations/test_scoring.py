from decimal import Decimal
from uuid import uuid4

from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationFeatures,
    RecommendationQuery,
    RecommendationSource,
)
from recipe_agent.domain.recommendations.scoring import rank_candidates


def features(score: str) -> RecommendationFeatures:
    value = Decimal(score)
    return RecommendationFeatures(
        ingredient_match=value,
        meal_type_fit=value,
        age_fit=value,
        rating=value,
        time_fit=value,
        scenario_fit=value,
        diversity=value,
    )


def candidate(
    name: str,
    score: str,
    *,
    allergens: frozenset[str] = frozenset(),
    minimum_age_years: int = 0,
    rating_count: int = 3,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        id=uuid4(),
        name=name,
        source=RecommendationSource.HOUSEHOLD,
        features=features(score),
        allergens=allergens,
        minimum_age_years=minimum_age_years,
        rating_count=rating_count,
    )


def test_age_and_allergy_restrictions_are_hard_filters() -> None:
    query = RecommendationQuery(
        household_id=uuid4(),
        ingredients=frozenset({"tomato"}),
        allergies=frozenset({"peanut"}),
        age_years=5,
    )

    results = rank_candidates(
        [
            candidate("Peanut noodles", "1", allergens=frozenset({"peanut"})),
            candidate("Adult curry", "1", minimum_age_years=12),
            candidate("Tomato soup", "0.7"),
        ],
        query,
    )

    assert [result.name for result in results] == ["Tomato soup"]


def test_scoring_orders_by_weighted_score_then_stable_name() -> None:
    query = RecommendationQuery(household_id=uuid4(), age_years=10)

    results = rank_candidates(
        [candidate("Zucchini Soup", "0.8"), candidate("Apple Soup", "0.8")],
        query,
    )

    assert [result.name for result in results] == ["Apple Soup", "Zucchini Soup"]
    assert results[0].score == Decimal("0.8")


def test_equal_scores_prefer_larger_rating_sample_before_name() -> None:
    query = RecommendationQuery(household_id=uuid4(), age_years=10)

    results = rank_candidates(
        [
            candidate("Alpha Soup", "0.8", rating_count=1),
            candidate("Zulu Soup", "0.8", rating_count=10),
        ],
        query,
    )

    assert [result.name for result in results] == ["Zulu Soup", "Alpha Soup"]
