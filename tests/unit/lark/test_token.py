import asyncio
import json

import httpx
import pytest

from recipe_agent.infrastructure.lark.token import LarkTenantTokenProvider, LarkTokenError


@pytest.mark.asyncio
async def test_tenant_token_is_cached_until_safe_expiry() -> None:
    requests: list[httpx.Request] = []
    now = 100.0

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "tenant_access_token": "tenant-secret",
                "expire": 7200,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = LarkTenantTokenProvider(
            http=http,
            app_id="cli_app",
            app_secret="app-secret",
            clock=lambda: now,
        )

        first = await provider.tenant_access_token()
        second = await provider.tenant_access_token()

    assert first == second == "tenant-secret"
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {
        "app_id": "cli_app",
        "app_secret": "app-secret",
    }


@pytest.mark.asyncio
async def test_concurrent_token_requests_share_one_refresh() -> None:
    calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": "shared-token", "expire": 7200},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = LarkTenantTokenProvider(
            http=http,
            app_id="cli_app",
            app_secret="app-secret",
        )
        tokens = await asyncio.gather(*(provider.tenant_access_token() for _ in range(5)))

    assert tokens == ["shared-token"] * 5
    assert calls == 1


@pytest.mark.asyncio
async def test_token_failure_is_bounded_and_does_not_expose_credentials() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10013, "msg": "bad app-secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = LarkTenantTokenProvider(
            http=http,
            app_id="cli_private",
            app_secret="very-private-secret",
        )
        with pytest.raises(LarkTokenError) as caught:
            await provider.tenant_access_token()

    rendered = str(caught.value)
    assert "very-private-secret" not in rendered
    assert "bad app-secret" not in rendered
    assert len(rendered) < 120
