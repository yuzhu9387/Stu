"""Passwordless authentication endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from recipe_agent.api.dependencies import IdentityDependency, ScopeDependency
from recipe_agent.domain.identity.service import (
    IdentityConflictError,
    InvalidTokenError,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkConsume(BaseModel):
    token: str


@router.post("/magic-links", status_code=status.HTTP_202_ACCEPTED)
async def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    service: IdentityDependency,
) -> dict[str, str]:
    delivery = await service.request_magic_link(str(payload.email))
    result = {"status": "accepted"}
    if request.app.state.settings.environment == "development":
        result["development_token"] = delivery.token
    return result


@router.post("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def consume_magic_link(
    payload: MagicLinkConsume,
    response: Response,
    request: Request,
    service: IdentityDependency,
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
        secure=request.app.state.settings.environment != "development",
        samesite="lax",
        path="/",
    )


class SessionResponse(BaseModel):
    account_id: UUID
    household_id: UUID
    email: EmailStr
    role: str


class LarkLinkCodeResponse(BaseModel):
    code: str


@router.get("/session", response_model=SessionResponse)
async def get_session(
    scope: ScopeDependency, service: IdentityDependency
) -> SessionResponse:
    try:
        identity = await service.get_session_identity(scope)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    return SessionResponse(
        account_id=identity.scope.account_id,
        household_id=identity.scope.household_id,
        email=identity.account.email,
        role=identity.role,
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    request: Request, response: Response, service: IdentityDependency
) -> None:
    token = request.cookies.get("recipe_session")
    if token:
        await service.delete_web_session(token)
    response.delete_cookie(
        "recipe_session",
        httponly=True,
        secure=request.app.state.settings.environment != "development",
        samesite="lax",
        path="/",
    )


@router.post(
    "/lark-link-codes",
    response_model=LarkLinkCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lark_link_code(
    scope: ScopeDependency, service: IdentityDependency
) -> LarkLinkCodeResponse:
    try:
        delivery = await service.create_lark_link_code(scope.account_id)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    except IdentityConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from error
    return LarkLinkCodeResponse(code=delivery.code)
