"""Authenticated explicit-click execution for signed suggested actions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

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


@router.post("/{token}", response_model=ActionResult)
async def consume_suggested_action(
    token: str,
    scope: ScopeDependency,
    service: ActionServiceDependency,
) -> ActionResult:
    try:
        return await service.consume(token, actor=scope)
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
