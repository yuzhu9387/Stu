import asyncio
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.conversation.actions import (
    ActionArguments,
    SaveRecipeMutationHandler,
    SuggestedActionRepository,
    SuggestedActionService,
)
from recipe_agent.domain.conversation.repository import AgentRunRepository
from recipe_agent.domain.conversation.responses import ActionArgument, SuggestedActionDraft
from recipe_agent.domain.identity.models import SuggestedActionRecord
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.recipes.models import Recipe
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.lark.crypto import ActionContextSigner


class RecordingHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ActionArguments, Any]] = []

    async def execute(self, *, actor, arguments, action_id) -> Mapping[str, object]:
        self.calls.append((actor, arguments, action_id))
        return {"saved": True, "name": arguments.name}


def _settings(database_url: str) -> Settings:
    return Settings(
        environment="development",
        database_url=database_url,
        session_signing_key="suggested-action-test-key",
        metrics_token="test-metrics-token",
    )


async def _create_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def _login(client: TestClient, email: str) -> dict[str, str]:
    delivery = client.post("/api/v1/auth/magic-links", json={"email": email})
    token = delivery.json()["development_token"]
    assert client.post("/api/v1/auth/sessions", json={"token": token}).status_code == 204
    return client.get("/api/v1/auth/session").json()


def _save_recipe_draft() -> SuggestedActionDraft:
    return SuggestedActionDraft(
        type="save_recipe",
        arguments=(
            ActionArgument(name="name", value_json='"Tomato soup"'),
            ActionArgument(
                name="ingredients",
                value_json='[{"name":"tomato","quantity":"2","unit":"cup"}]',
            ),
            ActionArgument(
                name="steps",
                value_json='[{"number":1,"text":"Simmer."}]',
            ),
        ),
    )


async def _count_rows(app) -> tuple[int, int]:
    async with app.state.session_factory() as session:
        return (
            await session.scalar(select(func.count()).select_from(Recipe)) or 0,
            await session.scalar(select(func.count()).select_from(SuggestedActionRecord)) or 0,
        )


def test_natural_language_completion_only_issues_consent_and_does_not_mutate(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'issue-only.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    identity = _login(client, "cook@example.com")
    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "Save this recipe",
            "locale": "en-US",
            "idempotency_key": "save-suggestion-1",
        },
    ).json()
    runs = AgentRunRepository(app.state.session_factory)
    claimed = asyncio.run(runs.claim(UUID(submitted["id"])))
    assert claimed is not None
    asyncio.run(
        runs.complete(
            claimed.id,
            {
                "answer": "Review the suggested save action.",
                "suggested_actions": [_save_recipe_draft().model_dump(mode="json")],
            },
        )
    )
    service = SuggestedActionService(
        repository=SuggestedActionRepository(app.state.session_factory),
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={
            "save_recipe": SaveRecipeMutationHandler(RecipeRepository(app.state.session_factory))
        },
        lifetime=timedelta(minutes=10),
    )

    issued = asyncio.run(
        service.issue(
            _save_recipe_draft(),
            actor=HouseholdScope(UUID(identity["account_id"]), UUID(identity["household_id"])),
            source_run_id=claimed.id,
        )
    )

    assert issued.type == "save_recipe"
    assert issued.token
    assert asyncio.run(_count_rows(app)) == (0, 1)


def test_authenticated_action_click_executes_once_and_returns_typed_result(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'consume-once.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    identity = _login(client, "clicker@example.com")
    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "Save this recipe",
            "locale": "en-US",
            "idempotency_key": "click-suggestion-1",
        },
    ).json()
    service = SuggestedActionService(
        repository=SuggestedActionRepository(app.state.session_factory),
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={
            "save_recipe": SaveRecipeMutationHandler(RecipeRepository(app.state.session_factory))
        },
    )
    app.state.suggested_action_service = service
    issued = asyncio.run(
        service.issue(
            _save_recipe_draft(),
            actor=HouseholdScope(UUID(identity["account_id"]), UUID(identity["household_id"])),
            source_run_id=UUID(submitted["id"]),
        )
    )

    first = client.post(f"/api/v1/agent/actions/{issued.token}")
    second = client.post(f"/api/v1/agent/actions/{issued.token}")

    assert first.status_code == 200
    assert first.json()["action_id"] == str(issued.id)
    assert first.json()["type"] == "save_recipe"
    assert first.json()["status"] == "succeeded"
    assert first.json()["result"]["name"] == "Tomato soup"
    assert second.status_code == 409
    assert second.json() == {"detail": "Suggested action was already consumed"}
    assert asyncio.run(_count_rows(app)) == (1, 1)


def test_action_endpoint_has_no_request_body_or_caller_selected_scope(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'body-free.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    operation = app.openapi()["paths"]["/api/v1/agent/actions/{token}"]["post"]

    assert "requestBody" not in operation
