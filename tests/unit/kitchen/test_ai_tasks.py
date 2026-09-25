"""Stu's work outlives the page that asked for it: stored chat and draft tasks."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import httpx

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.identity import models as _identity  # noqa: F401
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.ai import AIUnavailable, KitchenAI
from recipe_agent.domain.kitchen.engine import initial_state
from recipe_agent.infrastructure.jobs import kitchen_ai_tasks
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository, plan, recipe
from tests.unit.kitchen.test_compact_generation import compact_menu


class GatedProvider:
    """Answers only when released, like a slow model."""

    def __init__(self, *answers):
        self.answers, self.gate, self.calls = list(answers), asyncio.Event(), 0

    async def complete(self, messages, schema, *, vision=False):
        await self.gate.wait()
        self.calls += 1
        answer = self.answers[min(self.calls, len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return deepcopy(answer)


def workspace():
    state = initial_state()
    state["recipes"] = [recipe()]
    state["plans"] = [plan()]
    return state


async def client_for(session_factory, repository, provider):
    app = create_app(Settings(_env_file=None, environment="test"))
    app.state.session_factory = session_factory
    app.state.kitchen_ai = KitchenAI(repository, None, provider)
    scope = HouseholdScope(uuid4(), uuid4())
    app.dependency_overrides[get_household_scope] = lambda: scope
    transport = httpx.ASGITransport(app=app)
    return app, httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_a_chat_turn_keeps_running_and_is_found_again_after_a_reload(session_factory):
    repository = MemoryRepository(workspace())
    provider = GatedProvider(
        {"reply": "Nothing to change", "meals": [], "needsClarification": False}
    )
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:
            started = await client.post(
                "/api/v1/kitchen/ai-tasks/chat",
                json={"planId": "plan", "message": "Less rice", "expectedRevision": 0},
            )
            assert started.status_code == 200, started.text
            task = started.json()["task"]
            assert task["status"] == "running"
            # The message is part of the conversation at once.
            assert repository.state["plans"][0]["chat"][-1]["text"] == "Less rice"
            # A reload (or another page) finds the same turn, still running.
            latest = await client.get(
                "/api/v1/kitchen/ai-tasks/latest", params={"kind": "chat", "planId": "plan"}
            )
            assert latest.json()["task"]["id"] == task["id"]
            assert latest.json()["task"]["status"] == "running"
            # One turn at a time.
            busy = await client.post(
                "/api/v1/kitchen/ai-tasks/chat",
                json={
                    "planId": "plan",
                    "message": "And more",
                    "expectedRevision": repository.state["revision"],
                },
            )
            assert busy.status_code == 409
            provider.gate.set()
            await kitchen_ai_tasks.drain()
            done = (await client.get(f"/api/v1/kitchen/ai-tasks/{task['id']}")).json()["task"]
            assert done["status"] == "done"
            assert done["result"]["reply"] == "Nothing to change"
            assert "base" not in done["result"]
            last = repository.state["plans"][0]["chat"][-1]
            assert (last["role"], last["text"]) == ("assistant", "Nothing to change")
    finally:
        await app.state.runtime.aclose()


async def test_a_stored_proposal_is_applied_once_and_never_onto_a_changed_plan(session_factory):
    state = workspace()
    target = deepcopy(state["plans"][0]["meals"][8])
    target["steps"] = ["Reheat", "Serve"]
    answer = {"reply": "Simpler steps", "meals": [target], "needsClarification": False}
    repository = MemoryRepository(state)
    provider = GatedProvider(answer)
    provider.gate.set()
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:

            async def ask():
                response = await client.post(
                    "/api/v1/kitchen/ai-tasks/chat",
                    json={
                        "planId": "plan",
                        "message": "Simpler",
                        "mealIds": [target["id"]],
                        "expectedRevision": repository.state["revision"],
                    },
                )
                await kitchen_ai_tasks.drain()
                return response.json()["task"]["id"]

            first = await ask()
            applied = await client.post(f"/api/v1/kitchen/ai-tasks/{first}/apply")
            assert applied.status_code == 200, applied.text
            meal = next(m for m in repository.state["plans"][0]["meals"] if m["id"] == target["id"])
            assert meal["steps"] == ["Reheat", "Serve"]
            assert (await client.post(f"/api/v1/kitchen/ai-tasks/{first}/apply")).status_code == 409

            # The plan changes after Stu answers: the old suggestion is refused.
            second = await ask()
            repository.state["plans"][0]["meals"][0]["liked"] = True
            stale = await client.post(f"/api/v1/kitchen/ai-tasks/{second}/apply")
            assert stale.status_code == 409
            assert "changed after" in stale.json()["detail"]

            # Keeping the current meals closes the suggestion.
            third = await ask()
            kept = await client.post(f"/api/v1/kitchen/ai-tasks/{third}/dismiss")
            assert kept.json()["task"]["resolution"] == "dismissed"
    finally:
        await app.state.runtime.aclose()


async def test_a_week_is_drafted_in_the_background(session_factory):
    repository = MemoryRepository(initial_state())
    provider = GatedProvider(compact_menu())
    app, client = await client_for(session_factory, repository, provider)
    request = {"weekStart": "2026-09-21", "expectedRevision": 0, "operationId": "bg-draft"}
    try:
        async with client:
            started = await client.post("/api/v1/kitchen/ai-tasks/generate", json=request)
            assert started.status_code == 200, started.text
            task = started.json()["task"]
            # Asking again while it runs joins the same draft instead of a second one.
            again = await client.post("/api/v1/kitchen/ai-tasks/generate", json=request)
            assert again.json()["task"]["id"] == task["id"]
            # Something else changes meanwhile; the draft is still saved on top.
            await repository.command(
                None,
                {
                    "type": "tag.save",
                    "payload": {"name": "Meanwhile"},
                    "expectedRevision": repository.state["revision"],
                    "operationId": "meanwhile",
                },
            )
            provider.gate.set()
            await kitchen_ai_tasks.drain()
            latest = await client.get(
                "/api/v1/kitchen/ai-tasks/latest",
                params={"kind": "generate", "weekStart": "2026-09-21"},
            )
            done = latest.json()["task"]
            assert done["status"] == "done"
            assert [p["id"] for p in repository.state["plans"]] == [done["result"]["planId"]]
    finally:
        await app.state.runtime.aclose()


async def test_a_failed_draft_says_why_on_the_task(session_factory):
    repository = MemoryRepository(initial_state())
    provider = GatedProvider(AIUnavailable("AI provider unavailable"))
    provider.gate.set()
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:
            await client.post(
                "/api/v1/kitchen/ai-tasks/generate",
                json={"weekStart": "2026-09-21", "expectedRevision": 0, "operationId": "fails"},
            )
            await kitchen_ai_tasks.drain()
            latest = await client.get(
                "/api/v1/kitchen/ai-tasks/latest",
                params={"kind": "generate", "weekStart": "2026-09-21"},
            )
            failed = latest.json()["task"]
            assert failed["status"] == "failed"
            assert "unavailable" in failed["error"]
            assert repository.state["plans"] == []
    finally:
        await app.state.runtime.aclose()


async def test_server_remembers_clarification_scope_after_client_reload(session_factory):
    repository = MemoryRepository(workspace())
    provider = GatedProvider(
        {
            "reply": "What should change across the week?",
            "meals": [],
            "needsClarification": True,
            "options": ["Quicker weekdays", "More vegetables"],
        },
        compact_menu(),
    )
    provider.gate.set()
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:
            await client.post(
                "/api/v1/kitchen/ai-tasks/chat",
                json={
                    "planId": "plan",
                    "message": "Rebuild the whole week",
                    "expectedRevision": 0,
                },
            )
            await kitchen_ai_tasks.drain()
        # A new client does not have the old component's clarification flag.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as reloaded:
            started = await reloaded.post(
                "/api/v1/kitchen/ai-tasks/chat",
                json={
                    "planId": "plan",
                    "message": "周末可以丰富一点",
                    "expectedRevision": repository.state["revision"],
                },
            )
            assert started.status_code == 200, started.text
            assert started.json()["task"]["answering"] is True
            await kitchen_ai_tasks.drain()
            task_id = started.json()["task"]["id"]
            done = (await reloaded.get(f"/api/v1/kitchen/ai-tasks/{task_id}")).json()["task"]
            assert done["status"] == "done", done["error"]
            assert len(done["result"]["scope"].split(",")) == 21
            assert len(done["result"]["meals"]) == 21
    finally:
        await app.state.runtime.aclose()


async def test_confirm_is_durable_and_atomic_and_failure_keeps_draft(session_factory):
    repository = MemoryRepository(workspace())
    output = {
        "decisions": [
            {"recipeId": "rice", "prepareAhead": True, "reason": "Batch", "steps": ["Cook rice"]}
        ],
        "warnings": ["Check rice quantities"],
    }
    provider = GatedProvider(output)
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:
            request = {"planId": "plan", "expectedRevision": 0}
            started = await client.post("/api/v1/kitchen/ai-tasks/fulfillment", json=request)
            assert started.status_code == 200, started.text
            task = started.json()["task"]
            assert repository.state["plans"][0]["status"] == "draft"
            same = await client.post("/api/v1/kitchen/ai-tasks/fulfillment", json=request)
            assert same.json()["task"]["id"] == task["id"]
            found = await client.get(
                "/api/v1/kitchen/ai-tasks/latest", params={"kind": "fulfillment", "planId": "plan"}
            )
            assert found.json()["task"]["status"] == "running"
            provider.gate.set()
            await kitchen_ai_tasks.drain()
            done = (await client.get(f"/api/v1/kitchen/ai-tasks/{task['id']}")).json()["task"]
            assert done["status"] == "done", done
            assert repository.state["plans"][0]["status"] == "confirmed"
            assert repository.state["plans"][0]["fulfillment"]["warnings"] == output["warnings"]
    finally:
        await app.state.runtime.aclose()


async def test_confirm_rejects_a_fridge_change_during_ai_work(session_factory):
    repository = MemoryRepository(workspace())
    provider = GatedProvider(
        {
            "decisions": [
                {
                    "recipeId": "rice",
                    "prepareAhead": True,
                    "reason": "Batch",
                    "steps": ["Cook rice"],
                }
            ],
            "warnings": ["Check quantities"],
        }
    )
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:
            task = (
                await client.post(
                    "/api/v1/kitchen/ai-tasks/fulfillment",
                    json={"planId": "plan", "expectedRevision": 0},
                )
            ).json()["task"]
            repository.state["settings"]["people"] = 4
            provider.gate.set()
            await kitchen_ai_tasks.drain()
            done = (await client.get(f"/api/v1/kitchen/ai-tasks/{task['id']}")).json()["task"]
            assert done["status"] == "failed"
            assert "changed" in done["error"]
            assert repository.state["plans"][0]["status"] == "draft"
            assert not repository.state["plans"][0].get("fulfillment")
    finally:
        await app.state.runtime.aclose()


async def test_confirm_provider_failure_can_be_retried(session_factory):
    repository = MemoryRepository(workspace())
    provider = GatedProvider(
        AIUnavailable("API key missing"),
        {
            "decisions": [
                {
                    "recipeId": "rice",
                    "prepareAhead": True,
                    "reason": "Batch",
                    "steps": ["Cook rice"],
                }
            ],
            "warnings": ["Check quantities"],
        },
    )
    provider.gate.set()
    app, client = await client_for(session_factory, repository, provider)
    try:
        async with client:
            request = {"planId": "plan", "expectedRevision": 0}
            first = (
                await client.post("/api/v1/kitchen/ai-tasks/fulfillment", json=request)
            ).json()["task"]
            await kitchen_ai_tasks.drain()
            failed = (await client.get(f"/api/v1/kitchen/ai-tasks/{first['id']}")).json()["task"]
            assert failed["status"] == "failed"
            assert repository.state["plans"][0]["status"] == "draft"
            retry = (
                await client.post("/api/v1/kitchen/ai-tasks/fulfillment", json=request)
            ).json()["task"]
            await kitchen_ai_tasks.drain()
            assert retry["id"] != first["id"]
            assert repository.state["plans"][0]["status"] == "confirmed"
    finally:
        await app.state.runtime.aclose()
