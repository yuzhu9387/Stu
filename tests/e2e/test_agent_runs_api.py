import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.infrastructure.db.base import Base


def _settings(database_url: str) -> Settings:
    return Settings(
        environment="development",
        database_url=database_url,
        session_signing_key="test-session-signing-key",
        metrics_token="test-metrics-token",
    )


async def _create_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def _login(client: TestClient, email: str) -> None:
    requested = client.post("/api/v1/auth/magic-links", json={"email": email})
    token = requested.json()["development_token"]
    response = client.post("/api/v1/auth/sessions", json={"token": token})
    assert response.status_code == 204


def test_authenticated_submission_returns_accepted_and_is_idempotent(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'agent-api.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    _login(client, "cook@example.com")
    payload = {
        "message": "What should I cook?",
        "locale": "en-US",
        "idempotency_key": "api-request-1",
    }

    first = client.post("/api/v1/agent/runs", json=payload)
    second = client.post("/api/v1/agent/runs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()
    assert first.json()["status"] == "queued"
    assert UUID(first.json()["id"])
    assert UUID(first.json()["conversation_id"])

    fetched = client.get(f"/api/v1/agent/runs/{first.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == first.json()


def test_run_endpoints_require_authentication(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'agent-auth.db'}"
    asyncio.run(_create_schema(database_url))
    client = TestClient(create_app(_settings(database_url)))

    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "No session",
            "locale": "en-US",
            "idempotency_key": "unauthenticated-1",
        },
    )
    fetched = client.get(f"/api/v1/agent/runs/{UUID(int=0)}")

    assert submitted.status_code == 401
    assert fetched.status_code == 401


def test_account_cannot_read_or_continue_another_accounts_private_run(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'agent-privacy.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    alice = TestClient(app)
    bob = TestClient(app)
    _login(alice, "alice@example.com")
    _login(bob, "bob@example.com")
    created = alice.post(
        "/api/v1/agent/runs",
        json={
            "message": "Alice only",
            "locale": "en-US",
            "idempotency_key": "alice-api-1",
        },
    ).json()

    read = bob.get(f"/api/v1/agent/runs/{created['id']}")
    continued = bob.post(
        "/api/v1/agent/runs",
        json={
            "conversation_id": created["conversation_id"],
            "message": "Bob must not continue this",
            "locale": "en-US",
            "idempotency_key": "bob-api-1",
        },
    )

    assert read.status_code == 404
    assert continued.status_code == 404
