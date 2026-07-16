"""Recommendation inputs, features, and results."""

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecommendationSource(StrEnum):
    HOUSEHOLD = "household"
    GENERATED = "generated"


class RecommendationFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingredient_match: Decimal = Field(ge=0, le=1)
    meal_type_fit: Decimal = Field(ge=0, le=1)
    age_fit: Decimal = Field(ge=0, le=1)
    rating: Decimal = Field(ge=0, le=1)
    time_fit: Decimal = Field(ge=0, le=1)
    scenario_fit: Decimal = Field(ge=0, le=1)
    diversity: Decimal = Field(ge=0, le=1)
    difficulty_penalty: Decimal = Field(default=Decimal(0), ge=0)
    recent_repeat_penalty: Decimal = Field(default=Decimal(0), ge=0)
    negative_feedback_penalty: Decimal = Field(default=Decimal(0), ge=0)


class RecommendationCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str = Field(min_length=1)
    source: RecommendationSource
    features: RecommendationFeatures
    allergens: frozenset[str] = frozenset()
    minimum_age_years: int = Field(default=0, ge=0)
    rating_count: int = Field(default=0, ge=0)


class RecommendationQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    household_id: UUID
    ingredients: frozenset[str] = frozenset()
    allergies: frozenset[str] = frozenset()
    age_years: int | None = Field(default=None, ge=0)
    meal_type: str | None = None
    maximum_minutes: int | None = Field(default=None, ge=1)


class RecommendationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    source: RecommendationSource
    score: Decimal
    reason_codes: tuple[str, ...]
