"""Family membership and invitation endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from recipe_agent.api.dependencies import IdentityDependency, ScopeDependency
from recipe_agent.domain.identity.service import (
    IdentityConflictError,
    InvalidTokenError,
    PermissionDeniedError,
)

router = APIRouter(prefix="/api/v1/families", tags=["families"])


class FamilyInviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    expires_at: datetime


class FamilyInviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str


class FamilyMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    household_id: UUID
    role: str


@router.post("/invites", response_model=FamilyInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    scope: ScopeDependency, service: IdentityDependency
) -> FamilyInviteResponse:
    try:
        invite = await service.create_family_invite(scope)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
    return FamilyInviteResponse.model_validate(invite)


@router.post(
    "/invites/accept",
    response_model=FamilyMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_invite(
    payload: FamilyInviteAccept,
    scope: ScopeDependency,
    service: IdentityDependency,
) -> FamilyMembershipResponse:
    try:
        membership = await service.accept_family_invite(scope, payload.code)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    except IdentityConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return FamilyMembershipResponse.model_validate(membership)


@router.get("/current", response_model=FamilyMembershipResponse)
async def current_family(
    scope: ScopeDependency, service: IdentityDependency
) -> FamilyMembershipResponse:
    try:
        membership = await service.get_family_membership(scope)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    return FamilyMembershipResponse.model_validate(membership)
