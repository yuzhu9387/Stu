"""Authenticated family recipe list and detail DTO API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeDetail,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
    RecipeSummary,
)
from recipe_agent.domain.recipes.repository import RecipeNotFoundError, RecipeRepository

router = APIRouter(prefix="/api/v1/recipes", tags=["recipes"])


class RecipeListResponse(BaseModel):
    recipes: tuple[RecipeSummary, ...]


class RecipeMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=300)
    meal_type: str = Field(default="dinner", min_length=1, max_length=32)
    prep_minutes: int = Field(default=0, ge=0, le=1440)
    cook_minutes: int = Field(default=0, ge=0, le=1440)
    suitable_age_years: int = Field(default=0, ge=0, le=120)
    visibility: str = Field(default="family", pattern="^(private|family)$")
    image_url: str | None = Field(default=None, max_length=2000)
    ingredients: tuple[RecipeIngredientCandidate, ...] = ()
    steps: tuple[RecipeStepCandidate, ...] = ()

    def candidate(self) -> RecipeCandidate:
        return RecipeCandidate(
            name=self.name.strip(), ingredients=self.ingredients, steps=self.steps
        )


def get_recipe_repository(request: Request) -> RecipeRepository:
    return RecipeRepository(request.app.state.session_factory)


RecipeRepositoryDependency = Annotated[RecipeRepository, Depends(get_recipe_repository)]


@router.get("", response_model=RecipeListResponse)
async def list_recipes(
    scope: ScopeDependency, repository: RecipeRepositoryDependency
) -> RecipeListResponse:
    return RecipeListResponse(recipes=await repository.list_for_scope(scope))


@router.get("/{recipe_id}", response_model=RecipeDetail)
async def get_recipe(
    recipe_id: UUID,
    scope: ScopeDependency,
    repository: RecipeRepositoryDependency,
) -> RecipeDetail:
    try:
        return await repository.get_for_scope(scope, recipe_id)
    except RecipeNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.post("", response_model=RecipeDetail, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    payload: RecipeMutationRequest,
    scope: ScopeDependency,
    repository: RecipeRepositoryDependency,
) -> RecipeDetail:
    created = await repository.create(
        scope.account_id,
        scope.household_id,
        payload.candidate(),
        visibility=payload.visibility,
        meal_type=payload.meal_type,
        prep_minutes=payload.prep_minutes,
        cook_minutes=payload.cook_minutes,
        suitable_age_years=payload.suitable_age_years,
        image_url=payload.image_url,
    )
    return await repository.get_for_scope(scope, created.id)


@router.patch("/{recipe_id}", response_model=RecipeDetail)
async def update_recipe(
    recipe_id: UUID,
    payload: RecipeMutationRequest,
    scope: ScopeDependency,
    repository: RecipeRepositoryDependency,
) -> RecipeDetail:
    try:
        return await repository.update_for_owner(
            scope,
            recipe_id,
            payload.candidate(),
            visibility=payload.visibility,
            meal_type=payload.meal_type,
            prep_minutes=payload.prep_minutes,
            cook_minutes=payload.cook_minutes,
            suitable_age_years=payload.suitable_age_years,
            image_url=payload.image_url,
        )
    except RecipeNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: UUID,
    scope: ScopeDependency,
    repository: RecipeRepositoryDependency,
) -> Response:
    try:
        await repository.delete_for_owner(scope, recipe_id)
    except RecipeNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
