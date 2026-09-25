"""Exactly-three recommendation HTTP API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.recommendations.contracts import (
    RecommendationQuery,
    RecommendationResult,
)
from recipe_agent.domain.recommendations.service import RecommendationService

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredients: frozenset[str] = frozenset()
    allergies: frozenset[str] = frozenset()
    age_years: int | None = Field(default=None, ge=0)
    meal_type: str | None = None
    maximum_minutes: int | None = Field(default=None, ge=1)


class RecommendationResponse(BaseModel):
    recommendations: tuple[
        RecommendationResult,
        RecommendationResult,
        RecommendationResult,
    ]


def get_recommendation_service(request: Request) -> RecommendationService:
    service: RecommendationService | None = getattr(
        request.app.state, "recommendation_service", None
    )
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


@router.post("")
async def recommend(
    payload: RecommendationRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationResponse:
    query = RecommendationQuery(
        household_id=scope.household_id,
        ingredients=payload.ingredients,
        allergies=payload.allergies,
        age_years=payload.age_years,
        meal_type=payload.meal_type,
        maximum_minutes=payload.maximum_minutes,
    )
    return RecommendationResponse(recommendations=await service.recommend(query))
