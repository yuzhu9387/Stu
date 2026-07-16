"""Authenticated meal-plan and shopping-list read APIs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.planning.contracts import MealPlanSummary, ShoppingListView
from recipe_agent.domain.planning.repository import PlanNotFoundError, SqlPlanRepository

router = APIRouter(prefix="/api/v1", tags=["feature reads"])


class PlanListResponse(BaseModel):
    plans: tuple[MealPlanSummary, ...]


class ShoppingListResponse(BaseModel):
    shopping_lists: tuple[ShoppingListView, ...]


def get_plan_repository(request: Request) -> SqlPlanRepository:
    return SqlPlanRepository(request.app.state.session_factory)


PlanRepositoryDependency = Annotated[SqlPlanRepository, Depends(get_plan_repository)]


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    scope: ScopeDependency, repository: PlanRepositoryDependency
) -> PlanListResponse:
    return PlanListResponse(plans=await repository.list_for_scope(scope))


@router.get("/plans/{plan_id}", response_model=MealPlanSummary)
async def get_plan(
    plan_id: UUID,
    scope: ScopeDependency,
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    try:
        return await repository.get_for_scope(scope, plan_id)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.get("/shopping-lists", response_model=ShoppingListResponse)
async def list_shopping_lists(
    scope: ScopeDependency, repository: PlanRepositoryDependency
) -> ShoppingListResponse:
    return ShoppingListResponse(shopping_lists=await repository.list_shopping_for_scope(scope))


@router.get("/shopping-lists/{shopping_list_id}", response_model=ShoppingListView)
async def get_shopping_list(
    shopping_list_id: UUID,
    scope: ScopeDependency,
    repository: PlanRepositoryDependency,
) -> ShoppingListView:
    try:
        return await repository.get_shopping_for_scope(scope, shopping_list_id)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
