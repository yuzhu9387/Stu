"""Exactly-three recommendation orchestration."""

from typing import Protocol

from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationQuery,
    RecommendationResult,
)
from recipe_agent.domain.recommendations.scoring import rank_candidates


class HouseholdCandidateSource(Protocol):
    async def candidates(self, query: RecommendationQuery) -> list[RecommendationCandidate]: ...


class GeneratedCandidateSource(Protocol):
    async def generate(
        self, query: RecommendationQuery, count: int
    ) -> list[RecommendationCandidate]: ...


class RecommendationCapacityError(RuntimeError):
    """Three safe choices could not be produced."""


class RecommendationService:
    def __init__(
        self,
        *,
        household: HouseholdCandidateSource,
        generator: GeneratedCandidateSource,
    ) -> None:
        self._household = household
        self._generator = generator

    async def recommend(
        self, query: RecommendationQuery
    ) -> tuple[RecommendationResult, RecommendationResult, RecommendationResult]:
        household_candidates = await self._household.candidates(query)
        household_results = rank_candidates(household_candidates, query)[:3]
        shortage = 3 - len(household_results)
        generated_results: list[RecommendationResult] = []
        if shortage:
            generated_candidates = await self._generator.generate(query, shortage)
            generated_results = rank_candidates(generated_candidates, query)[:shortage]
        combined = household_results + generated_results
        if len(combined) != 3:
            raise RecommendationCapacityError("Could not produce three safe recommendations")
        return combined[0], combined[1], combined[2]
