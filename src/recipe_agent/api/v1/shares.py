"""Privacy-safe share creation HTTP API."""

from datetime import timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.sharing.projection import ShareRecipeSnapshot
from recipe_agent.domain.sharing.service import ShareService

router = APIRouter(prefix="/api/v1/shares", tags=["sharing"])


class CreateShareRequest(ShareRecipeSnapshot):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expires_in_hours: int = Field(default=24, ge=1, le=24 * 30, exclude=True)


class ShareTokenResponse(BaseModel):
    token: str


def get_share_service(request: Request) -> ShareService:
    service: ShareService | None = getattr(request.app.state, "share_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_share(
    payload: CreateShareRequest,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> ShareTokenResponse:
    del scope
    snapshot = cast(dict[str, JsonValue], payload.model_dump(mode="json"))
    delivery = await service.create_snapshot(
        snapshot,
        expires_in=timedelta(hours=payload.expires_in_hours),
    )
    return ShareTokenResponse(token=delivery.token)
