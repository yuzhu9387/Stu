"""Authenticated API scope dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from recipe_agent.domain.identity.service import HouseholdScope, IdentityService


def get_household_scope(request: Request) -> HouseholdScope:
    scope: HouseholdScope | None = getattr(request.state, "household_scope", None)
    if scope is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return scope


def get_identity_service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity_service
    return service


ScopeDependency = Annotated[HouseholdScope, Depends(get_household_scope)]
IdentityDependency = Annotated[IdentityService, Depends(get_identity_service)]
