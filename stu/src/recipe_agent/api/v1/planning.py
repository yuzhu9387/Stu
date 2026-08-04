"""Weekly meal planning HTTP API."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import MealPlan, MealPlanSummary, PlanItem, PlanSlot
from recipe_agent.domain.planning.repository import PlanNotFoundError, SqlPlanRepository
from recipe_agent.domain.planning.service import PlanningService

router = APIRouter(prefix="/api/v1/plans", tags=["planning"])


class CreateWeekRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    week_start: date
    slots: tuple[PlanSlot, ...]


class PlanItemMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    slot: Literal["breakfast", "lunch", "dinner", "snack"]
    recipe_id: UUID
    recipe_name: str = Field(min_length=1, max_length=300)

    def to_item(self, *, item_id: UUID | None = None) -> PlanItem:
        return PlanItem(
            id=item_id or uuid4(),
            day=self.day,
            slot=self.slot,
            recipe_id=self.recipe_id,
            recipe_name=self.recipe_name.strip(),
            reason_codes=("manually_selected",),
        )


class CreatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(default="Weekly plan", min_length=1, max_length=200)
    week_start: date
    items: tuple[PlanItemMutation, ...] = ()


class UpdatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = Field(default=None, min_length=1, max_length=200)
    week_start: date | None = None


class GeneratePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(default="AI weekly plan", min_length=1, max_length=200)
    week_start: date
    days: tuple[date, ...] = Field(min_length=1, max_length=7)
    meals: tuple[Literal["breakfast", "lunch", "dinner"], ...] = Field(min_length=1, max_length=3)
    preferences: tuple[str, ...] = Field(default=(), max_length=12)
    people_count: int = Field(default=2, ge=1, le=20)
    notes: str | None = Field(default=None, max_length=2000)


def get_planning_service(request: Request) -> PlanningService:
    service: PlanningService | None = getattr(request.app.state, "planning_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def get_plan_repository(request: Request) -> SqlPlanRepository:
    return SqlPlanRepository(request.app.state.session_factory)


PlanRepositoryDependency = Annotated[SqlPlanRepository, Depends(get_plan_repository)]


@router.post("/weeks", response_model=MealPlan, status_code=status.HTTP_201_CREATED)
async def create_week(
    payload: CreateWeekRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> MealPlan:
    return await service.create_week(
        scope.account_id,
        scope.household_id,
        payload.week_start,
        payload.slots,
    )


@router.post("", response_model=MealPlanSummary, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: CreatePlanRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    plan = MealPlan(
        id=uuid4(),
        owner_account_id=scope.account_id,
        household_id=scope.household_id,
        title=payload.title.strip(),
        week_start=payload.week_start,
        version=1,
        items=tuple(item.to_item() for item in payload.items),
    )
    await repository.save(plan)
    return await repository.get_for_scope(scope, plan.id)


@router.post("/generate", response_model=MealPlanSummary, status_code=status.HTTP_201_CREATED)
async def generate_plan(
    payload: GeneratePlanRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    service: Annotated[PlanningService, Depends(get_planning_service)],
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    plan = await service.create_week(
        scope.account_id,
        scope.household_id,
        payload.week_start,
        tuple(PlanSlot(day=day, slot=meal) for day in payload.days for meal in payload.meals),
        title=payload.title.strip(),
        generated_by_ai=True,
        preferences=payload.preferences,
        people_count=payload.people_count,
        notes=payload.notes,
    )
    return await repository.get_for_scope(scope, plan.id)


@router.patch("/{plan_id}", response_model=MealPlanSummary)
async def update_plan(
    plan_id: UUID,
    payload: UpdatePlanRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    try:
        return await repository.update_metadata_for_owner(
            scope, plan_id, title=payload.title, week_start=payload.week_start
        )
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: UUID,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: PlanRepositoryDependency,
) -> Response:
    try:
        await repository.delete_for_owner(scope, plan_id)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{plan_id}/items", response_model=MealPlanSummary, status_code=status.HTTP_201_CREATED
)
async def create_plan_item(
    plan_id: UUID,
    payload: PlanItemMutation,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    try:
        return await repository.add_item_for_owner(scope, plan_id, payload.to_item())
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.patch("/{plan_id}/items/{item_id}", response_model=MealPlanSummary)
async def update_plan_item(
    plan_id: UUID,
    item_id: UUID,
    payload: PlanItemMutation,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    try:
        return await repository.update_item_for_owner(
            scope, plan_id, item_id, payload.to_item(item_id=item_id)
        )
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.delete("/{plan_id}/items/{item_id}", response_model=MealPlanSummary)
async def delete_plan_item(
    plan_id: UUID,
    item_id: UUID,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: PlanRepositoryDependency,
) -> MealPlanSummary:
    try:
        return await repository.delete_item_for_owner(scope, plan_id, item_id)
    except PlanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
