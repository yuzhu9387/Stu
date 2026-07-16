import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import recipe_agent.app as app_module
from recipe_agent.app import create_app
from recipe_agent.config import Settings


def test_health_endpoints_report_application_state() -> None:
    app = create_app(Settings(environment="test"))

    class Ready:
        async def check(self) -> None:
            return None

    app.state.readiness = Ready()
    client = TestClient(app)

    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_readiness_returns_bounded_503_when_dependency_is_down() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    class Down:
        async def check(self) -> None:
            raise RuntimeError("postgresql://user:secret@private-host/internal")

    app.state.readiness = Down()
    response = TestClient(app).get("/health/ready")

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
        response = await asyncio.wait_for(client.get("/health/ready"), timeout=0.2)

    assert response.status_code == 503
    assert response.json() == {"detail": "Application dependencies are unavailable"}


def test_local_up_starts_complete_stack() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "local-up:\n\tdocker compose -f infra/compose.yaml up -d --build" in makefile
