"""Passwordless authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from recipe_agent.config import Settings, get_settings
from recipe_agent.domain.identity.service import IdentityService, InvalidTokenError

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkConsume(BaseModel):
    token: str


def get_identity_service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity_service
    return service


@router.post("/magic-links", status_code=status.HTTP_202_ACCEPTED)
async def request_magic_link(
    payload: MagicLinkRequest,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> dict[str, str]:
    await service.request_magic_link(str(payload.email))
    return {"status": "accepted"}


@router.post("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def consume_magic_link(
    payload: MagicLinkConsume,
    response: Response,
    service: Annotated[IdentityService, Depends(get_identity_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        authenticated = await service.consume_magic_link(payload.token)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    response.set_cookie(
        "recipe_session",
        authenticated.session_token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path="/",
    )
