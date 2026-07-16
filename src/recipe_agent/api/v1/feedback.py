"""Recipe feedback HTTP API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.domain.feedback.contracts import FeedbackOutcome
from recipe_agent.domain.feedback.service import FeedbackService
from recipe_agent.domain.identity.service import HouseholdScope

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


def get_feedback_service(request: Request) -> FeedbackService:
    service: FeedbackService | None = getattr(request.app.state, "feedback_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


@router.post("/{recipe_id}", status_code=status.HTTP_201_CREATED)
async def record_feedback(
    recipe_id: UUID,
    payload: FeedbackRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackOutcome:
    return await service.record(scope.household_id, recipe_id, payload.text)
