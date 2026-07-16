"""Resolve opaque web-session cookies into authenticated household scope."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from recipe_agent.domain.identity.service import IdentityService


class SessionScopeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, identity: IdentityService) -> None:
        super().__init__(app)
        self._identity = identity

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        token = request.cookies.get("recipe_session")
        if token:
            request.state.household_scope = await self._identity.resolve_web_session(token)
        return await call_next(request)
