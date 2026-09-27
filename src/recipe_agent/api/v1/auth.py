"""Authentication endpoints: email and password for everyone, plus a
passwordless shortcut that exists only in development."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from recipe_agent.api.dependencies import IdentityDependency, ScopeDependency
from recipe_agent.domain.identity.passwords import MAX_LENGTH, WeakPasswordError
from recipe_agent.domain.identity.service import (
    AccountExistsError,
    AccountLockedError,
    IdentityConflictError,
    InvalidCredentialsError,
    InvalidTokenError,
    McpTokenView,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkConsume(BaseModel):
    token: str


class PasswordCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_LENGTH)


def _development(request: Request) -> bool:
    return bool(request.app.state.settings.environment == "development")


def _production(request: Request) -> bool:
    return bool(request.app.state.settings.environment == "production")


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        "recipe_session",
        token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=not _development(request),
        samesite="lax",
        path="/",
    )


@router.get("/methods")
async def sign_in_methods(request: Request) -> dict[str, bool]:
    """How this server lets people in: always a password; locally, also a shortcut."""
    return {"password": True, "developmentLink": _development(request)}


@router.post("/register", status_code=status.HTTP_204_NO_CONTENT)
async def register(
    payload: PasswordCredentials,
    response: Response,
    request: Request,
    service: IdentityDependency,
) -> None:
    try:
        authenticated = await service.register(str(payload.email), payload.password)
    except WeakPasswordError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AccountExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already uses this email. Sign in instead.",
        ) from error
    _set_session_cookie(response, request, authenticated.session_token)


@router.post("/sign-in", status_code=status.HTTP_204_NO_CONTENT)
async def sign_in(
    payload: PasswordCredentials,
    response: Response,
    request: Request,
    service: IdentityDependency,
) -> None:
    try:
        authenticated = await service.sign_in(str(payload.email), payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect."
        ) from error
    except AccountLockedError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again in 15 minutes.",
        ) from error
    _set_session_cookie(response, request, authenticated.session_token)


@router.post("/magic-links", status_code=status.HTTP_202_ACCEPTED)
async def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    service: IdentityDependency,
) -> dict[str, str]:
    # Nothing delivers a link, so the shortcut never exists in production.
    if _production(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    delivery = await service.request_magic_link(str(payload.email))
    result = {"status": "accepted"}
    if _development(request):
        result["development_token"] = delivery.token
    return result


@router.post("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def consume_magic_link(
    payload: MagicLinkConsume,
    response: Response,
    request: Request,
    service: IdentityDependency,
) -> None:
    if _production(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        authenticated = await service.consume_magic_link(payload.token)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
    _set_session_cookie(response, request, authenticated.session_token)


class SessionResponse(BaseModel):
    account_id: UUID
    household_id: UUID
    email: EmailStr
    role: str


class LarkLinkCodeResponse(BaseModel):
    code: str


@router.get("/session", response_model=SessionResponse)
async def get_session(scope: ScopeDependency, service: IdentityDependency) -> SessionResponse:
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
async def delete_session(request: Request, response: Response, service: IdentityDependency) -> None:
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


class McpTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _token_json(view: McpTokenView) -> dict[str, str | None]:
    return {
        "id": str(view.id),
        "name": view.name,
        "createdAt": view.created_at.isoformat(),
        "lastUsedAt": view.last_used_at.isoformat() if view.last_used_at else None,
    }


# Access tokens for AI (MCP) clients. Managed with the signed-in web session
# only: a token can use the kitchen, never mint or list tokens.
@router.get("/mcp-tokens")
async def list_mcp_tokens(
    scope: ScopeDependency, service: IdentityDependency
) -> dict[str, list[dict[str, str | None]]]:
    return {"tokens": [_token_json(view) for view in await service.list_mcp_tokens(scope)]}


@router.post("/mcp-tokens", status_code=status.HTTP_201_CREATED)
async def create_mcp_token(
    payload: McpTokenCreate, scope: ScopeDependency, service: IdentityDependency
) -> dict[str, str | None]:
    try:
        view, token = await service.create_mcp_token(scope, payload.name)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    # The only time the token itself is ever returned.
    return {**_token_json(view), "token": token}


@router.delete("/mcp-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_mcp_token(
    token_id: UUID, scope: ScopeDependency, service: IdentityDependency
) -> None:
    if not await service.revoke_mcp_token(scope, token_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
