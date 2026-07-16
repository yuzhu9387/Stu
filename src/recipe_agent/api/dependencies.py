"""Authenticated API scope dependencies."""

from fastapi import HTTPException, Request, status

from recipe_agent.domain.identity.service import HouseholdScope


def get_household_scope(request: Request) -> HouseholdScope:
    scope: HouseholdScope | None = getattr(request.state, "household_scope", None)
    if scope is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return scope
