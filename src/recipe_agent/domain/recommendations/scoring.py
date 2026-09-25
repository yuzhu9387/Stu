"""Deterministic recommendation safety filtering and scoring."""

from decimal import Decimal

from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationQuery,
    RecommendationResult,
    RecommendationSource,
)


def rank_candidates(
    candidates: list[RecommendationCandidate],
    query: RecommendationQuery,
) -> list[RecommendationResult]:
    eligible = [candidate for candidate in candidates if _eligible(candidate, query)]
    ranked = sorted(
        eligible,
        key=lambda candidate: (
            -_score(candidate),
            0 if candidate.source is RecommendationSource.HOUSEHOLD else 1,
            -candidate.rating_count,
            candidate.name.casefold(),
            str(candidate.id),
        ),
    )
    return [_to_result(candidate) for candidate in ranked]


def _eligible(candidate: RecommendationCandidate, query: RecommendationQuery) -> bool:
    normalized_allergies = {item.casefold() for item in query.allergies}
    normalized_candidate = {item.casefold() for item in candidate.allergens}
    if normalized_allergies & normalized_candidate:
        return False
    return query.age_years is None or candidate.minimum_age_years <= query.age_years


def _to_result(candidate: RecommendationCandidate) -> RecommendationResult:
    score = _score(candidate)
    features = candidate.features
    reasons: list[str] = []
    if candidate.source is RecommendationSource.HOUSEHOLD:
        reasons.append("from_household_library")
    if features.ingredient_match >= Decimal("0.5"):
        reasons.append("ingredient_match")
    if features.rating >= Decimal("0.5"):
        reasons.append("well_rated")
    return RecommendationResult(
        id=candidate.id,
        owner_account_id=candidate.owner_account_id,
        name=candidate.name,
        source=candidate.source,
        score=score,
        reason_codes=tuple(reasons),
    )


def _score(candidate: RecommendationCandidate) -> Decimal:
    features = candidate.features
    return (
        features.ingredient_match * Decimal("0.25")
        + features.meal_type_fit * Decimal("0.15")
        + features.age_fit * Decimal("0.15")
        + features.rating * Decimal("0.20")
        + features.time_fit * Decimal("0.10")
        + features.scenario_fit * Decimal("0.10")
        + features.diversity * Decimal("0.05")
        - features.difficulty_penalty
        - features.recent_repeat_penalty
        - features.negative_feedback_penalty
    )
