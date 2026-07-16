import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import create_async_engine

from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.identity.models import FamilyMembership, WebSession
from recipe_agent.infrastructure.db.base import Base


def _settings(database_url: str, *, environment: str = "test") -> Settings:
    return Settings(
        environment=environment,
        database_url=database_url,
        session_signing_key="test-session-signing-key",
        metrics_token="test-metrics-token",
    )


async def _create_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _seed_session(app):
    delivery = await app.state.identity_service.request_magic_link("cook@example.com")
    return await app.state.identity_service.consume_magic_link(delivery.token)


def test_session_cookie_resolves_account_and_family_scope(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'session.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    seeded_session = asyncio.run(_seed_session(app))
    client = TestClient(app)
    client.cookies.set("recipe_session", seeded_session.session_token)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "account_id": str(seeded_session.account.id),
        "household_id": str(seeded_session.household.id),
        "email": "cook@example.com",
        "role": "owner",
    }
    assert "token" not in response.text
    assert "hash" not in response.text


def test_expired_or_membership_inconsistent_sessions_are_unauthenticated(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'invalid-sessions.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    expired = asyncio.run(_seed_session(app))

    async def expire_session() -> None:
        async with app.state.identity_service._session_factory() as session:
            await session.execute(
                update(WebSession)
                .where(WebSession.account_id == expired.account.id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()

    asyncio.run(expire_session())
    client = TestClient(app)
    client.cookies.set("recipe_session", expired.session_token)
    assert client.get("/api/v1/auth/session").status_code == 401

    valid = asyncio.run(_seed_session(app))

    async def remove_membership() -> None:
        async with app.state.identity_service._session_factory() as session:
            await session.execute(
                delete(FamilyMembership).where(
                    FamilyMembership.account_id == valid.account.id
                )
            )
            await session.commit()

    asyncio.run(remove_membership())
    client.cookies.set("recipe_session", valid.session_token)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_delete_session_invalidates_server_record_and_clears_cookie(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'logout.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    seeded = asyncio.run(_seed_session(app))
    client = TestClient(app)
    client.cookies.set("recipe_session", seeded.session_token)

    response = client.delete("/api/v1/auth/session")

    assert response.status_code == 204
    assert "recipe_session=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    client.cookies.set("recipe_session", seeded.session_token)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_magic_link_token_is_exposed_only_in_development(tmp_path) -> None:
    for environment in ("test", "production"):
        database_url = f"sqlite+aiosqlite:///{tmp_path / f'{environment}.db'}"
        asyncio.run(_create_schema(database_url))
        client = TestClient(create_app(_settings(database_url, environment=environment)))
        response = client.post(
            "/api/v1/auth/magic-links", json={"email": f"{environment}@example.com"}
        )
        assert response.status_code == 202
        assert response.json() == {"status": "accepted"}

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'development.db'}"
    asyncio.run(_create_schema(database_url))
    client = TestClient(create_app(_settings(database_url, environment="development")))
    response = client.post(
        "/api/v1/auth/magic-links", json={"email": "developer@example.com"}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["development_token"]


def test_owner_family_and_lark_link_endpoints_use_session_scope(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'family-api.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    seeded = asyncio.run(_seed_session(app))
    client = TestClient(app)
    client.cookies.set("recipe_session", seeded.session_token)

    current = client.get("/api/v1/families/current")
    invite = client.post("/api/v1/families/invites")
    lark_code = client.post("/api/v1/auth/lark-link-codes")

    assert current.status_code == 200
    assert current.json()["role"] == "owner"
    assert invite.status_code == 201
    assert invite.json()["code"]
    assert lark_code.status_code == 201
    assert lark_code.json()["code"]
