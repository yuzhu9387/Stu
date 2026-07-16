import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.conversation.actions import (
    ActionArguments,
    CreatePlanArguments,
    CreatePlanMutationHandler,
    CreateShareArguments,
    CreateShareMutationHandler,
    ReplacePlanItemArguments,
    ReplacePlanItemMutationHandler,
    SaveRecipeArguments,
    SaveRecipeMutationHandler,
    SuggestedActionRepository,
    SuggestedActionService,
)
from recipe_agent.domain.conversation.repository import AgentRunRepository
from recipe_agent.domain.conversation.responses import ActionArgument, SuggestedActionDraft
from recipe_agent.domain.identity.models import ActionMutationReceipt, SuggestedActionRecord
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import PlanSlot
from recipe_agent.domain.planning.models import MealPlanRecord
from recipe_agent.domain.planning.repository import SqlPlanRepository
from recipe_agent.domain.planning.service import PlanningService
from recipe_agent.domain.recipes.models import Recipe
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.domain.recommendations.contracts import (
    RecommendationQuery,
    RecommendationResult,
    RecommendationSource,
)
from recipe_agent.domain.sharing.models import ShareSnapshotRecord
from recipe_agent.domain.sharing.repository import SqlShareRepository
from recipe_agent.domain.sharing.service import ShareService
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.db.outbox import OutboxEvent
from recipe_agent.infrastructure.lark.crypto import ActionContextSigner


class RecordingHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ActionArguments, Any]] = []

    async def execute(self, *, actor, arguments, action_id) -> Mapping[str, object]:
        self.calls.append((actor, arguments, action_id))
        return {"saved": True, "name": arguments.name}


class FixedRecommendations:
    def __init__(self) -> None:
        self.results = tuple(
            RecommendationResult(
                id=uuid4(),
                name=f"Meal {index}",
                source=RecommendationSource.HOUSEHOLD,
                score=Decimal("0.9"),
                reason_codes=("family_favorite",),
            )
            for index in range(3)
        )

    async def recommend(
        self, query: RecommendationQuery
    ) -> tuple[RecommendationResult, RecommendationResult, RecommendationResult]:
        del query
        return self.results


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


def _create_plan_draft(day: date) -> SuggestedActionDraft:
    return SuggestedActionDraft(
        type="create_plan",
        arguments=(
            ActionArgument(name="week_start", value_json=f'"{day.isoformat()}"'),
            ActionArgument(
                name="slots",
                value_json=f"[{ {'day': day.isoformat(), 'slot': 'dinner'} }]".replace("'", '"'),
            ),
        ),
    )


def _replace_plan_draft(plan_id: UUID, day: date) -> SuggestedActionDraft:
    return SuggestedActionDraft(
        type="replace_plan_item",
        arguments=(
            ActionArgument(name="plan_id", value_json=f'"{plan_id}"'),
            ActionArgument(name="day", value_json=f'"{day.isoformat()}"'),
        ),
    )


def _create_share_draft(recipe_id: UUID) -> SuggestedActionDraft:
    return SuggestedActionDraft(
        type="create_share",
        arguments=(
            ActionArgument(name="id", value_json=f'"{recipe_id}"'),
            ActionArgument(name="name", value_json='"Soup"'),
            ActionArgument(name="ingredients", value_json='["tomato"]'),
            ActionArgument(name="steps", value_json='["Simmer"]'),
            ActionArgument(name="expires_in_hours", value_json="24"),
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

    first = client.post("/api/v1/agent/actions/execute", json={"token": issued.token})
    second = client.post("/api/v1/agent/actions/execute", json={"token": issued.token})

    assert first.status_code == 202
    assert first.json()["action_id"] == str(issued.id)
    assert first.json()["type"] == "save_recipe"
    assert first.json()["status"] == "queued"
    assert first.json()["result"] is None
    assert second.status_code == 409
    assert second.json() == {"detail": "Suggested action was already consumed"}

    completed = asyncio.run(service.execute_queued(issued.id))
    status_response = client.get(f"/api/v1/agent/actions/{issued.id}")

    assert completed.status == "succeeded"
    assert status_response.status_code == 200
    assert status_response.json()["result"]["name"] == "Tomato soup"
    assert asyncio.run(_count_rows(app)) == (1, 1)


def test_save_recipe_mutation_is_idempotent_by_action_id_after_worker_crash(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'save-receipt.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    identity = _login(client, "receipt@example.com")
    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "Save it once",
            "locale": "en-US",
            "idempotency_key": "receipt-run-1",
        },
    ).json()
    scope = HouseholdScope(UUID(identity["account_id"]), UUID(identity["household_id"]))
    service = SuggestedActionService(
        repository=SuggestedActionRepository(app.state.session_factory),
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={},
    )
    issued = asyncio.run(
        service.issue(
            _save_recipe_draft(),
            actor=scope,
            source_run_id=UUID(submitted["id"]),
        )
    )
    handler = SaveRecipeMutationHandler(RecipeRepository(app.state.session_factory))
    arguments = SaveRecipeArguments(
        name="Tomato soup",
        ingredients=({"name": "tomato", "quantity": "2", "unit": "cup"},),
        steps=({"number": 1, "text": "Simmer."},),
    )

    first = asyncio.run(handler.execute(actor=scope, arguments=arguments, action_id=issued.id))
    second = asyncio.run(handler.execute(actor=scope, arguments=arguments, action_id=issued.id))

    assert first == second
    assert asyncio.run(_count_rows(app)) == (1, 1)


def test_worker_recovers_crash_after_mutation_commit_without_duplicate_write(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'crash-recovery.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    identity = _login(client, "crash-recovery@example.com")
    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "Recover this save",
            "locale": "en-US",
            "idempotency_key": "crash-recovery-run-1",
        },
    ).json()
    scope = HouseholdScope(UUID(identity["account_id"]), UUID(identity["household_id"]))
    repository = SuggestedActionRepository(app.state.session_factory)
    handler = SaveRecipeMutationHandler(RecipeRepository(app.state.session_factory))
    clock = [datetime(2026, 7, 16, tzinfo=UTC)]
    service = SuggestedActionService(
        repository=repository,
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={"save_recipe": handler},
        now=lambda: clock[0],
    )
    issued = asyncio.run(
        service.issue(
            _save_recipe_draft(),
            actor=scope,
            source_run_id=UUID(submitted["id"]),
        )
    )
    asyncio.run(service.consume(issued.token, actor=scope))
    leased = asyncio.run(
        repository.claim_for_execution(
            issued.id,
            now=clock[0],
            lease_duration=timedelta(seconds=30),
        )
    )
    assert leased is not None
    arguments = SaveRecipeArguments(
        name="Tomato soup",
        ingredients=({"name": "tomato", "quantity": "2", "unit": "cup"},),
        steps=({"number": 1, "text": "Simmer."},),
    )
    asyncio.run(handler.execute(actor=scope, arguments=arguments, action_id=issued.id))
    clock[0] += timedelta(seconds=31)
    assert asyncio.run(repository.recover_expired(now=clock[0])) == 1

    result = asyncio.run(service.execute_queued(issued.id))

    assert result.status == "succeeded"
    assert result.result is not None
    assert result.result["name"] == "Tomato soup"
    assert asyncio.run(_count_rows(app)) == (1, 1)


def test_create_and_replace_plan_mutations_are_idempotent_by_action_id(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'plan-receipts.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    identity = _login(client, "planner-receipt@example.com")
    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "Plan once",
            "locale": "en-US",
            "idempotency_key": "plan-receipt-run-1",
        },
    ).json()
    scope = HouseholdScope(UUID(identity["account_id"]), UUID(identity["household_id"]))
    monday = date(2026, 7, 20)
    repository = SqlPlanRepository(app.state.session_factory)
    planning = PlanningService(repository=repository, recommendations=FixedRecommendations())
    service = SuggestedActionService(
        repository=SuggestedActionRepository(app.state.session_factory),
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={},
    )
    create_issued = asyncio.run(
        service.issue(
            _create_plan_draft(monday),
            actor=scope,
            source_run_id=UUID(submitted["id"]),
        )
    )
    create_handler = CreatePlanMutationHandler(planning)
    create_arguments = CreatePlanArguments(
        week_start=monday,
        slots=(PlanSlot(day=monday, slot="dinner"),),
    )

    first_created = asyncio.run(
        create_handler.execute(actor=scope, arguments=create_arguments, action_id=create_issued.id)
    )
    second_created = asyncio.run(
        create_handler.execute(actor=scope, arguments=create_arguments, action_id=create_issued.id)
    )

    replace_issued = asyncio.run(
        service.issue(
            _replace_plan_draft(first_created.id, monday),
            actor=scope,
            source_run_id=UUID(submitted["id"]),
        )
    )
    replace_handler = ReplacePlanItemMutationHandler(planning)
    replace_arguments = ReplacePlanItemArguments(plan_id=first_created.id, day=monday)
    first_replaced = asyncio.run(
        replace_handler.execute(
            actor=scope, arguments=replace_arguments, action_id=replace_issued.id
        )
    )
    second_replaced = asyncio.run(
        replace_handler.execute(
            actor=scope, arguments=replace_arguments, action_id=replace_issued.id
        )
    )
    worker_service = SuggestedActionService(
        repository=SuggestedActionRepository(app.state.session_factory),
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={
            "create_plan": create_handler,
            "replace_plan_item": replace_handler,
        },
    )
    asyncio.run(worker_service.consume(create_issued.token, actor=scope))
    create_status = asyncio.run(worker_service.execute_queued(create_issued.id))
    asyncio.run(worker_service.consume(replace_issued.token, actor=scope))
    replace_status = asyncio.run(worker_service.execute_queued(replace_issued.id))

    assert first_created == second_created
    assert first_replaced == second_replaced
    assert first_replaced.version == 2
    assert create_status.status == "succeeded"
    assert replace_status.status == "succeeded"

    async def plan_count() -> int:
        async with app.state.session_factory() as session:
            return await session.scalar(select(func.count()).select_from(MealPlanRecord)) or 0

    assert asyncio.run(plan_count()) == 1


def test_create_share_is_idempotent_and_never_persists_plaintext_delivery(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'share-receipt.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    client = TestClient(app)
    identity = _login(client, "share-receipt@example.com")
    submitted = client.post(
        "/api/v1/agent/runs",
        json={
            "message": "Share once",
            "locale": "en-US",
            "idempotency_key": "share-receipt-run-1",
        },
    ).json()
    scope = HouseholdScope(UUID(identity["account_id"]), UUID(identity["household_id"]))
    draft = _create_share_draft(uuid4())
    shares = ShareService(
        repository=SqlShareRepository(app.state.session_factory),
        action_token_key="deterministic-share-delivery-key",
    )
    handler = CreateShareMutationHandler(shares)
    consent = SuggestedActionService(
        repository=SuggestedActionRepository(app.state.session_factory),
        signer=ActionContextSigner("action-consent-signing-key"),
        handlers={"create_share": handler},
    )
    app.state.suggested_action_service = consent
    issued = asyncio.run(consent.issue(draft, actor=scope, source_run_id=UUID(submitted["id"])))
    arguments = CreateShareArguments(
        id=uuid4(),
        name="Soup",
        ingredients=("tomato",),
        steps=("Simmer",),
        expires_in_hours=24,
    )

    first = asyncio.run(handler.execute(actor=scope, arguments=arguments, action_id=issued.id))
    second = asyncio.run(handler.execute(actor=scope, arguments=arguments, action_id=issued.id))
    delivery = asyncio.run(handler.delivery(actor=scope, action_id=issued.id))
    asyncio.run(consent.consume(issued.token, actor=scope))
    completed = asyncio.run(consent.execute_queued(issued.id))
    safe_status = client.get(f"/api/v1/agent/actions/{issued.id}")
    delivery_status = client.get(
        f"/api/v1/agent/actions/{issued.id}", params={"include_delivery": "true"}
    )

    assert first == second
    assert set(first) == {"share_id", "expires_at"}
    assert delivery.token
    assert completed.result == first
    assert safe_status.status_code == 200
    assert safe_status.json()["delivery"] is None
    assert delivery.token not in safe_status.text
    assert delivery_status.status_code == 200
    assert delivery_status.json()["delivery"]["token"] == delivery.token

    async def persisted_values() -> tuple[int, str]:
        async with app.state.session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(ShareSnapshotRecord))
            receipt = await session.get(ActionMutationReceipt, issued.id)
            action = await session.get(SuggestedActionRecord, issued.id)
            share = await session.scalar(
                select(ShareSnapshotRecord).where(ShareSnapshotRecord.source_action_id == issued.id)
            )
            outbox_payloads = tuple(await session.scalars(select(OutboxEvent.payload_json)))
            assert receipt is not None
            assert action is not None
            assert share is not None
            persisted_text = "\n".join(
                (
                    receipt.result_json,
                    action.token_hash,
                    action.arguments_json,
                    action.result_json or "",
                    share.token_hash,
                    share.snapshot_json,
                    *outbox_payloads,
                )
            )
            return count or 0, persisted_text

    share_count, persisted_text = asyncio.run(persisted_values())
    assert share_count == 1
    assert delivery.token not in persisted_text
    assert issued.token not in persisted_text


def test_action_endpoint_accepts_only_a_body_token_and_never_places_it_in_path(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'body-free.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url))
    paths = app.openapi()["paths"]
    operation = paths["/api/v1/agent/actions/execute"]["post"]

    assert all("{token}" not in path for path in paths)
    assert operation["requestBody"]["required"] is True
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ExecuteSuggestedAction")
    body_schema = app.openapi()["components"]["schemas"]["ExecuteSuggestedAction"]
    assert body_schema["required"] == ["token"]
    assert body_schema["additionalProperties"] is False
