"""Authenticated family recipe list and detail DTO API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.recipes.contracts import RecipeDetail, RecipeSummary
from recipe_agent.domain.recipes.repository import RecipeNotFoundError, RecipeRepository

router = APIRouter(prefix="/api/v1/recipes", tags=["recipes"])


class RecipeListResponse(BaseModel):
    recipes: tuple[RecipeSummary, ...]


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
