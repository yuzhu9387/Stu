import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

import recipe_agent.app as app_module
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.sharing.service import ShareRecord


@pytest.mark.parametrize(
    ("configured", "origin", "allowed"),
    [
        ("http://localhost:13107", "http://127.0.0.1:13107", True),
        ("http://127.0.0.1:13107", "http://localhost:13107", True),
        ("http://localhost:13107", "http://127.0.0.1:9999", False),
        ("https://kitchen.example", "http://127.0.0.1:13107", False),
    ],
)
def test_loopback_frontend_origins_keep_the_configured_port(
    client_factory, configured, origin, allowed
):
    app = create_app(Settings(_env_file=None, environment="test", web_origin=configured))
    response = client_factory(app).options(
        "/api/v1/kitchen", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)


def test_health_endpoints_report_application_state(
    client_factory,
) -> None:
    app = create_app(Settings(environment="test"))

    class Ready:
        async def check(self) -> None:
            return None

    app.state.readiness = Ready()
    client = client_factory(app)

    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_readiness_returns_bounded_503_when_dependency_is_down(
    client_factory,
) -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    class Down:
        async def check(self) -> None:
            raise RuntimeError("postgresql://user:secret@private-host/internal")

    app.state.readiness = Down()
    response = client_factory(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Application dependencies are unavailable"}
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_readiness_times_out_as_503_when_dependency_hangs(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "READINESS_TIMEOUT_SECONDS", 0.01, raising=False)
    app = create_app(Settings(_env_file=None, environment="test"))

    class Hanging:
        async def check(self) -> None:
            await asyncio.Event().wait()

    app.state.readiness = Hanging()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # The dependency waits forever, so any finite bound proves readiness
        # timed out rather than hung. A tight wall-clock budget only measured
        # how busy the machine was.
        response = await asyncio.wait_for(client.get("/health/ready"), timeout=5)

    assert response.status_code == 503
    assert response.json() == {"detail": "Application dependencies are unavailable"}


def test_local_up_starts_complete_stack() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "COMPOSE := docker compose --env-file .env -f infra/compose.yaml" in makefile
    assert "local-up:\n\t$(COMPOSE) up -d --build" in makefile


async def test_lifespan_closes_runtime_when_context_exits_with_error(monkeypatch) -> None:
    app = create_app(Settings(_env_file=None, environment="test"))
    close = app.state.runtime.aclose
    closed = False

    async def record_close() -> None:
        nonlocal closed
        await close()
        closed = True

    monkeypatch.setattr(app.state.runtime, "aclose", record_close)
    with pytest.raises(RuntimeError, match="test context failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("test context failed")
    assert closed


def test_public_share_endpoint_returns_only_allowlisted_recipe_fields(
    client_factory,
) -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    class Shares:
        async def resolve_token(self, token: str) -> ShareRecord:
            assert token == "public-token"
            return ShareRecord(
                token_hash="hash-only",
                snapshot={
                    "id": str(uuid4()),
                    "name": "Family Soup",
                    "ingredients": ["tomato"],
                    "steps": ["Simmer."],
                },
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    app.state.share_service = Shares()
    response = client_factory(app).get("/api/v1/public/shares/public-token")

    assert response.status_code == 200
    assert set(response.json()) == {"id", "name", "ingredients", "steps"}


def production_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        session_signing_key="s" * 32,
        metrics_token="m" * 32,
        action_signing_key="a" * 32,
        openai_api_key="sk-test-only",
        **overrides,
    )


def test_production_offers_passwords_and_no_passwordless_shortcut(client_factory) -> None:
    client = client_factory(create_app(production_settings()))
    assert client.get("/api/v1/auth/methods").json() == {
        "password": True,
        "developmentLink": False,
    }
    assert client.post("/api/v1/auth/magic-links", json={"email": "a@b.co"}).status_code == 404
    assert client.post("/api/v1/auth/sessions", json={"token": "x"}).status_code == 404


def test_behind_the_worker_only_relayed_requests_reach_the_api(client_factory) -> None:
    client = client_factory(create_app(production_settings(edge_proxy_token="e" * 48)))
    assert client.get("/api/v1/auth/methods").status_code == 404
    assert (
        client.get("/api/v1/auth/methods", headers={"X-Stu-Proxy-Token": "wrong"}).status_code
        == 404
    )
    relayed = client.get("/api/v1/auth/methods", headers={"X-Stu-Proxy-Token": "e" * 48})
    assert relayed.status_code == 200
    # Cloud Run's own health probes do not pass through the Worker.
    assert client.get("/health/live").json() == {"status": "alive"}
