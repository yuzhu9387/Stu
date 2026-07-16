"""Validated recipe extraction contracts."""

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecipeIngredientCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    quantity: Decimal | None = None
    unit: str | None = None


class RecipeStepCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int = Field(ge=1)
    text: str = Field(min_length=1)


class RecipeCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    ingredients: tuple[RecipeIngredientCandidate, ...]
    steps: tuple[RecipeStepCandidate, ...]

    @model_validator(mode="after")
    def require_ingredients_for_steps(self) -> Self:
        if self.steps and not self.ingredients:
            raise ValueError("Recipe steps require at least one ingredient")
        return self


class RecipeView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    household_id: UUID
    name: str
    ingredients: tuple[RecipeIngredientCandidate, ...]
    steps: tuple[RecipeStepCandidate, ...]
