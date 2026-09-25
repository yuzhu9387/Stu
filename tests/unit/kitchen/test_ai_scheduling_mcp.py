import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from recipe_agent.api.v1.kitchen_mcp import dispatch
from recipe_agent.config import Settings
from recipe_agent.domain.kitchen.ai import (
    AIUnavailable,
    ChatRequest,
    ExtractRequest,
    GenerateRequest,
    KitchenAI,
    KitchenProvider,
    image_content,
)
from recipe_agent.domain.kitchen.engine import apply_command, initial_state
from recipe_agent.domain.kitchen.scheduling import due_week, schedule_tasks
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.jobs.kitchen import claim_job, finish_job
from tests.unit.kitchen.compact_fixtures import compact_fixture


class MemoryRepository:
    def __init__(self, state):
        self.state = deepcopy(state)
        self.scopes = []

    async def get(self, scope):
        self.scopes.append(scope)
        return deepcopy(self.state)

    async def command(self, scope, command):
        self.scopes.append(scope)
        result = apply_command(self.state, command, "test")
        self.state = result["state"]
        return result


class FakeProvider:
    def __init__(self, result):
        self.result, self.requests = result, []

    async def complete(self, messages, schema, *, vision=False):
        self.requests.append((messages, schema, vision))
        return deepcopy(self.result)


def recipe():
    return {
        "id": "rice",
        "name": "Rice",
        "type": "Carbs",
        "mealTypes": ["dinner"],
        "tags": [],
        "servings": 3,
        "activeMinutes": 2,
        "elapsedMinutes": 10,
        "ingredients": [{"name": "Rice", "quantity": 1, "unit": "cup"}],
        "steps": ["Cook rice"],
        "liked": False,
        "source": "household",
    }


def plan():
    return {
        "id": "plan",
        "weekStart": "2026-09-21",
        "status": "draft",
        "version": 1,
        "prompt": "",
        "prep": [],
        "chat": [],
        "meals": [
            {
                "id": f"m{d}{slot}",
                "day": f"2026-09-{21 + d}",
                "slot": slot,
                "components": [
                    {
                        "id": f"c{d}{slot}",
                        "name": "Rice",
                        "type": "Carbs",
                        "portions": 3,
                        "recipeId": "rice",
                    }
                ],
                "activeMinutes": 2,
                "elapsedMinutes": 10,
                "steps": ["Cook rice"],
                "status": "planned",
                "liked": False,
                "locked": False,
            }
            for d in range(7)
            for slot in ("breakfast", "lunch", "dinner")
        ],
    }


def test_resources_and_dependencies():
    tasks = [
        dict(id="a", activeMinutes=10, elapsedMinutes=60, equipment=["oven"]),
        dict(id="b", activeMinutes=10, elapsedMinutes=30, equipment=["pot"]),
        dict(id="c", activeMinutes=5, elapsedMinutes=20, equipment=["oven"]),
        dict(id="d", activeMinutes=5, elapsedMinutes=5, dependencies=["b"]),
    ]
    result = schedule_tasks(tasks)
    assert result["activeMinutes"] == 30
    assert result["elapsedMinutes"] == 80
    assert result["tasks"][1]["startMinutes"] == 10
    assert next(t for t in result["tasks"] if t["id"] == "c")["startMinutes"] == 60
    with pytest.raises(ValueError, match="cyclic"):
        schedule_tasks([dict(id="x", dependencies=["x"])])
    with pytest.raises(ValueError, match="Complete timing"):
        schedule_tasks([dict(id="x", activeMinutes=0, elapsedMinutes=0)])


def test_friday_timezone_catchup_and_monday_boundary():
    settings = {"timezone": "America/Los_Angeles", "generateTime": "17:00"}
    assert due_week(datetime(2026, 9, 18, 23, 59, tzinfo=UTC), settings) is None
    assert due_week(datetime(2026, 9, 19, 0, tzinfo=UTC), settings) == "2026-09-21"
    assert due_week(datetime(2026, 9, 21, 6, 59, tzinfo=UTC), settings) == "2026-09-21"
    assert due_week(datetime(2026, 9, 21, 7, tzinfo=UTC), settings) is None


async def test_generation_complete_and_idempotent():
    repo = MemoryRepository(initial_state())
    provider = FakeProvider(compact_fixture({"recipes": [recipe()], "plan": plan()}))
    ai = KitchenAI(repo, None, provider, compact_weekly=False)
    request = GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="gen")
    result = await ai.generate("household", request)
    assert len(result["state"]["plans"][0]["meals"]) == 21
    assert result["state"]["recipes"][0]["name"] == "Rice"
    await ai.generate("household", request)
    assert len(provider.requests) == 1
    assert set(repo.scopes) == {"household"}


async def test_generation_rejects_title_only_and_allergy():
    for bad in ({"ingredients": []}, {"name": "Peanut rice"}):
        state = initial_state()
        state["settings"]["allergies"] = ["peanut"]
        repo = MemoryRepository(state)
        ai = KitchenAI(
            repo,
            None,
            FakeProvider(compact_fixture({"recipes": [{**recipe(), **bad}], "plan": plan()})),
            compact_weekly=False,
        )
        with pytest.raises(ValueError):
            await ai.generate(
                "scope",
                GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="bad"),
            )
        assert repo.state["revision"] == 0


async def test_chat_selected_boundary_and_locked_history():
    state = initial_state()
    state.update(recipes=[recipe()], plans=[plan()])
    original = state["plans"][0]["meals"][0]
    other = state["plans"][0]["meals"][1]
    provider = FakeProvider({"reply": "Changed", "meals": [other], "needsClarification": False})
    repo = MemoryRepository(state)
    ai = KitchenAI(repo, None, provider, compact_weekly=False)
    request = ChatRequest(
        planId="plan", message="Change this", mealIds=[original["id"]], expectedRevision=0
    )

    def dishes():
        return [
            (meal["id"], [part.get("recipeId") for part in meal["components"]])
            for meal in repo.state["plans"][0]["meals"]
        ]

    meals = dishes()
    refused = await ai.chat("scope", request)
    assert refused["meals"] == [] and "scope" in refused["reply"]
    provider.result["meals"] = [original]
    repo.state["plans"][0]["meals"][0]["locked"] = True
    # The refusal is part of the conversation now, so the revision moved.
    request = request.model_copy(update={"expectedRevision": repo.state["revision"]})
    refused = await ai.chat("scope", request)
    assert refused["meals"] == [] and "scope" in refused["reply"]
    # Nothing was applied: the chat is the only thing that changed.
    assert dishes() == meals


async def test_image_content_is_sent_to_vision_and_text_preserved():
    data = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 20).decode()
    provider = FakeProvider({"recipes": [recipe()]})
    result = await KitchenAI(None, None, provider, compact_weekly=False).extract(
        "scope", ExtractRequest(text="Original rice recipe", imageData=data)
    )
    messages, _, vision = provider.requests[0]
    assert vision
    assert messages[1]["content"][1]["image_url"]["url"] == data
    assert result["recipes"][0]["source"] == "Original rice recipe"
    with pytest.raises(ValueError):
        image_content("data:image/svg+xml;base64,PHN2Zz4=")


async def test_provider_failure_is_not_fake_success():
    async def failure(**kwargs):
        raise RuntimeError("secret provider data")

    with pytest.raises(AIUnavailable, match="unavailable"):
        await KitchenProvider(Settings(), failure).complete([], {})


async def test_full_week_provider_has_its_own_deadline_without_duplicate_transport_retries():
    options = []

    async def completion(**kwargs):
        options.append(kwargs)
        return {"choices": [{"message": {"content": "{}"}}]}

    provider = KitchenProvider(
        Settings(
            litellm_timeout_seconds=15,
            kitchen_generation_reasoning_effort="low",
            kitchen_generation_timeout_seconds=240,
            kitchen_chat_reasoning_effort="low",
        ),
        completion,
    )
    await provider.complete([], {"title": "Generation", "properties": {"plan": {}, "recipes": {}}})
    assert options[-1]["timeout"] == 240
    assert options[-1]["max_retries"] == 0
    assert options[-1]["verbosity"] == "low"
    assert options[-1]["reasoning_effort"] == "low"
    await provider.complete([], {"title": "CompactGeneration"})
    assert options[-1]["timeout"] == 240
    assert options[-1]["max_retries"] == 0
    assert options[-1]["reasoning_effort"] == "low"
    # A chat answer reasons a little, within the ordinary deadline.
    await provider.complete([], {"title": "Proposal"})
    assert options[-1]["timeout"] == 15
    assert options[-1]["reasoning_effort"] == "low"
    await provider.complete([], {"title": "Extraction"})
    assert options[-1]["timeout"] == 15


async def test_mcp_protocol_scoped_commands_and_invalid_arguments():
    repo = MemoryRepository(initial_state())
    ai = SimpleNamespace(repository=repo)
    result = await dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        ai,
        "scope",
    )
    assert result["result"]["capabilities"]["tools"]
    result = await dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "kitchen_command",
                "arguments": {
                    "type": "tag.save",
                    "payload": {"name": "Test"},
                    "expectedRevision": 0,
                    "operationId": "tag",
                },
            },
        },
        ai,
        "scope",
    )
    assert not result["result"]["isError"]
    assert repo.state["tags"] == ["Test"]
    result = await dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "kitchen_read", "arguments": {"householdId": "another"}},
        },
        ai,
        "scope",
    )
    assert result["result"]["isError"]
    assert (
        await dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, ai, "scope")
        is None
    )


async def test_durable_claim_dedupe_expired_lease_and_bounded_retry():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine)
    household = uuid4()
    now = datetime(2026, 9, 19, tzinfo=UTC)
    assert await claim_job(factory, household, "2026-09-21", now) == 1
    assert await claim_job(factory, household, "2026-09-21", now) is None
    later = now + timedelta(minutes=21)
    assert await claim_job(factory, household, "2026-09-21", later) == 2
    await finish_job(factory, household, "2026-09-21", 2, later, "Provider unavailable")
    assert await claim_job(factory, household, "2026-09-21", later) is None
    assert await claim_job(factory, household, "2026-09-21", later + timedelta(minutes=11)) == 3
    await finish_job(factory, household, "2026-09-21", 3, later, "Provider unavailable")
    assert await claim_job(factory, household, "2026-09-21", later + timedelta(hours=1)) is None
    await engine.dispose()


async def test_chat_proposal_records_history_without_applying_meal():
    state = initial_state()
    state.update(recipes=[recipe()], plans=[plan()])
    meal = deepcopy(state["plans"][0]["meals"][0])
    meal["components"][0]["portions"] = 2
    repo = MemoryRepository(state)
    ai = KitchenAI(
        repo,
        None,
        FakeProvider({"reply": "Use two portions", "meals": [meal], "needsClarification": False}),
        compact_weekly=False,
    )
    result = await ai.chat(
        "scope",
        ChatRequest(
            planId="plan", message="Two portions", mealIds=[meal["id"]], expectedRevision=0
        ),
    )
    assert result["meals"][0]["components"][0]["portions"] == 2
    assert repo.state["plans"][0]["meals"][0]["components"][0]["portions"] == 3
    assert len(repo.state["plans"][0]["chat"]) == 2
    assert repo.state["revision"] == 1


async def test_mcp_endpoint_requires_scope_and_rejects_foreign_origin():
    import httpx
    from fastapi import FastAPI

    from recipe_agent.api.dependencies import get_household_scope
    from recipe_agent.api.v1.kitchen_mcp import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = Settings()
    app.state.kitchen_ai = SimpleNamespace(repository=MemoryRepository(initial_state()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        assert (await client.post("/api/v1/kitchen/mcp", json=message)).status_code == 401
        app.dependency_overrides[get_household_scope] = lambda: "household"
        response = await client.post(
            "/api/v1/kitchen/mcp", json=message, headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 403
        response = await client.post("/api/v1/kitchen/mcp", json=message)
        assert response.status_code == 200
        assert len(response.json()["result"]["tools"]) == 5
        assert (await client.get("/api/v1/kitchen/mcp")).status_code == 405


@pytest.mark.parametrize(
    ("message", "count", "expected"),
    [
        ("Change all breakfasts", 7, {"breakfast"}),
        ("调整周二晚餐", 1, {"dinner"}),
        ("Change Tuesday dinner", 1, {"dinner"}),
        ("调整周末", 6, {"breakfast", "lunch", "dinner"}),
        ("调整整周", 21, {"breakfast", "lunch", "dinner"}),
        ("Monday breakfast and Tuesday dinner", 2, {"breakfast", "dinner"}),
        ("周一和周二晚餐", 2, {"dinner"}),
        ("Make it easier", 0, set()),
    ],
)
def test_bilingual_explicit_scope(message, count, expected):
    from recipe_agent.domain.kitchen.ai import resolve_meal_scope

    meals = plan()["meals"]
    selected = resolve_meal_scope(message, meals)
    assert len(selected) == count
    assert {m["slot"] for m in meals if m["id"] in selected} == expected


async def test_generation_cannot_replace_confirmed_history():
    state = initial_state()
    state.update(plans=[{**plan(), "status": "confirmed"}])
    provider = FakeProvider({})
    ai = KitchenAI(MemoryRepository(state), None, provider, compact_weekly=False)
    with pytest.raises(ValueError, match="already confirmed"):
        await ai.generate(
            "scope", GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="new")
        )
    assert not provider.requests


async def test_worker_scheduler_failure_retries_and_cancels(monkeypatch):
    import asyncio

    import recipe_agent.worker as worker

    calls = []

    async def failed_scan(*args):
        calls.append("scan")
        raise RuntimeError("secret must not leak")

    async def cancelled_sleep(seconds):
        assert seconds == 60
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "run_due_kitchen_jobs", failed_scan)
    monkeypatch.setattr(worker.asyncio, "sleep", cancelled_sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.kitchen_generation_loop(None, Settings())
    assert calls == ["scan"]


def test_baking_passive_tail_excluded_but_active_and_oven_conflicts_count():
    from recipe_agent.domain.kitchen.scheduling import validate_plan_timing

    state = initial_state()
    base = {
        "id": "bake",
        "name": "Bread",
        "type": "Baking",
        "activeMinutes": 20,
        "elapsedMinutes": 360,
        "equipment": ["oven"],
        "dependencies": [],
    }
    ordinary = {
        "id": "soup",
        "name": "Soup",
        "type": "Other",
        "activeMinutes": 30,
        "elapsedMinutes": 60,
        "equipment": ["pot"],
        "dependencies": [],
    }
    proposal = {"meals": [], "prep": [base, ordinary]}
    validate_plan_timing(state, proposal)
    summary = schedule_tasks(proposal["prep"])
    assert summary["ordinaryElapsedMinutes"] == 80
    assert summary["elapsedMinutes"] == 360
    assert summary["bakingWaitingMinutes"] == 280
    with pytest.raises(ValueError, match="Ordinary prep"):
        validate_plan_timing(
            state, {"meals": [], "prep": [base, {**ordinary, "equipment": ["oven"]}]}
        )
    with pytest.raises(ValueError, match="active minutes including baking"):
        validate_plan_timing(state, {"meals": [], "prep": [{**base, "activeMinutes": 250}]})
