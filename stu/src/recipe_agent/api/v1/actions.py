"""Authenticated explicit-click execution for signed suggested actions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.conversation.actions import (
    ActionExecutionError,
    ActionResult,
    InvalidSuggestedActionError,
    SuggestedActionConflictError,
    SuggestedActionNotFoundError,
    SuggestedActionService,
)

router = APIRouter(prefix="/api/v1/agent/actions", tags=["agent-actions"])


def get_suggested_action_service(request: Request) -> SuggestedActionService:
    service: SuggestedActionService | None = getattr(
        request.app.state, "suggested_action_service", None
    )
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


ActionServiceDependency = Annotated[SuggestedActionService, Depends(get_suggested_action_service)]


class ExecuteSuggestedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str = Field(min_length=1, max_length=4096)


@router.post(
    "/execute",
    response_model=ActionResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def consume_suggested_action(
    payload: ExecuteSuggestedAction,
    scope: ScopeDependency,
    service: ActionServiceDependency,
) -> ActionResult:
    try:
        return await service.consume(payload.token, actor=scope)
    except InvalidSuggestedActionError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Suggested action token is invalid or expired",
        ) from error
    except SuggestedActionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggested action not found",
        ) from error
    except SuggestedActionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Suggested action was already consumed",
        ) from error
    except ActionExecutionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Suggested action execution failed",
        ) from error


@router.post(
    "/{action_id}/execute",
    response_model=ActionResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def consume_suggested_action_by_id(
    action_id: UUID,
    scope: ScopeDependency,
    service: ActionServiceDependency,
) -> ActionResult:
    try:
        return await service.consume_by_id(action_id, actor=scope)
    except InvalidSuggestedActionError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Suggested action token is invalid or expired",
        ) from error
    except SuggestedActionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggested action not found",
        ) from error
    except SuggestedActionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Suggested action was already consumed",
        ) from error


@router.get("/{action_id}", response_model=ActionResult)
async def get_suggested_action_status(
    action_id: UUID,
    scope: ScopeDependency,
    service: ActionServiceDependency,
    include_delivery: bool = False,
) -> ActionResult:
    try:
        return await service.get_status(
            action_id,
            actor=scope,
            include_delivery=include_delivery,
        )
    except SuggestedActionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggested action not found",
        ) from error
    except (InvalidSuggestedActionError, ActionExecutionError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Suggested action status is unavailable",
        ) from error
