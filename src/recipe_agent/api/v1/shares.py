"""Privacy-safe share creation HTTP API."""

from datetime import timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.sharing.projection import ShareRecipeSnapshot
from recipe_agent.domain.sharing.repository import SqlShareRepository
from recipe_agent.domain.sharing.service import InvalidShareTokenError, ShareService, ShareSummary

router = APIRouter(prefix="/api/v1/shares", tags=["sharing"])
public_router = APIRouter(prefix="/api/v1/public/shares", tags=["public sharing"])


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
    snapshot = cast(dict[str, JsonValue], payload.model_dump(mode="json"))
    delivery = await service.create_snapshot(
        snapshot,
        owner_account_id=scope.account_id,
        household_id=scope.household_id,
        expires_in=timedelta(hours=payload.expires_in_hours),
    )
    return ShareTokenResponse(token=delivery.token)


class ShareListResponse(BaseModel):
    shares: tuple[ShareSummary, ...]


def get_share_repository(request: Request) -> SqlShareRepository:
    return SqlShareRepository(request.app.state.session_factory)


ShareRepositoryDependency = Annotated[SqlShareRepository, Depends(get_share_repository)]


@router.get("", response_model=ShareListResponse)
async def list_shares(
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: ShareRepositoryDependency,
) -> ShareListResponse:
    return ShareListResponse(shares=await repository.list_for_scope(scope))


@router.get("/{share_id}", response_model=ShareSummary)
async def get_share(
    share_id: UUID,
    scope: Annotated[HouseholdScope, Depends(get_household_scope)],
    repository: ShareRepositoryDependency,
) -> ShareSummary:
    result = await repository.get_for_scope(scope, share_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return result


@public_router.get("/{token}", response_model=ShareRecipeSnapshot)
async def get_public_share(
    token: str,
    service: Annotated[ShareService, Depends(get_share_service)],
) -> ShareRecipeSnapshot:
    try:
        record = await service.resolve_token(token)
        return ShareRecipeSnapshot.model_validate(record.snapshot)
    except (InvalidShareTokenError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
