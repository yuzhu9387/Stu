"""Cached tenant token acquisition for the Lark international API."""

import asyncio
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class LarkTokenError(RuntimeError):
    """Tenant authentication failed without exposing provider details."""


class _TenantTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: int
    tenant_access_token: str | None = None
    expire: int = Field(default=0, ge=0)


class LarkTenantTokenProvider:
    """Cache a tenant token and serialize refreshes inside one process."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.larksuite.com",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._clock = clock
        self._token: str | None = None
        self._refresh_at = 0.0
        self._lock = asyncio.Lock()

    async def tenant_access_token(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._refresh_at:
            return self._token
        async with self._lock:
            now = self._clock()
            if self._token is not None and now < self._refresh_at:
                return self._token
            token, expires_in = await self._refresh()
            self._token = token
            self._refresh_at = now + max(1, expires_in - 60)
            return token

    async def invalidate(self, token: str) -> None:
        """Invalidate only the rejected generation, preserving newer refreshes."""

        async with self._lock:
            if self._token == token:
                self._token = None
                self._refresh_at = 0.0

    async def _refresh(self) -> tuple[str, int]:
        try:
            response = await self._http.post(
                f"{self._base_url}/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            response.raise_for_status()
            payload = _TenantTokenResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError):
            raise LarkTokenError("Unable to acquire Lark tenant token") from None
        if payload.code != 0 or not payload.tenant_access_token or payload.expire <= 0:
            raise LarkTokenError("Unable to acquire Lark tenant token")
        return payload.tenant_access_token, payload.expire


__all__ = ["LarkTenantTokenProvider", "LarkTokenError"]
