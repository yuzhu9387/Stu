"""Weekly meal planning HTTP API."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import MealPlan, PlanSlot
from recipe_agent.domain.planning.service import PlanningService

router = APIRouter(prefix="/api/v1/plans", tags=["planning"])


class CreateWeekRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    week_start: date
    slots: tuple[PlanSlot, ...]


def get_planning_service(request: Request) -> PlanningService:
    service: PlanningService | None = getattr(request.app.state, "planning_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


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
