"""Persistent scheduler preferences, failure status, and explicit retry."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi import FastAPI

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.api.v1.kitchen import router
from recipe_agent.config import Settings
from recipe_agent.domain.identity.models import Account, Household
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.ai import AIUnavailable
from recipe_agent.domain.kitchen.repository import KitchenRepository
from recipe_agent.infrastructure.jobs.kitchen import run_due_kitchen_jobs


async def test_scheduled_generation_reads_saved_prompt_and_exposes_retry(session_factory):
    account, household = uuid4(), uuid4()
    async with session_factory() as session, session.begin():
        session.add(Account(id=account, email="jobs@example.test"))
        session.add(Household(id=household, owner_account_id=account))
    scope = HouseholdScope(account, household)
    repository = KitchenRepository(session_factory)
    await repository.command(
        scope,
        {
            "type": "planning.prompt",
            "payload": {"weekStart": "2026-09-21", "prompt": "优先菠菜"},
            "expectedRevision": 0,
            "operationId": "prompt",
        },
    )

    class Unavailable:
        async def complete(self, messages, schema, **kwargs):
            assert "优先菠菜" in messages[1]["content"]
            raise AIUnavailable("AI provider unavailable; configure a key")

    settings = Settings(_env_file=None)
    now = datetime(2026, 9, 19, 1, tzinfo=UTC)
    assert (
        await run_due_kitchen_jobs(session_factory, settings, now=now, provider=Unavailable()) == 0
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.session_factory = session_factory
    app.dependency_overrides[get_household_scope] = lambda: scope
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/kitchen/generation-jobs")
        assert response.status_code == 200
        job = response.json()["jobs"][0]
        assert job["weekStart"] == "2026-09-21"
        assert job["status"] == "retry"
        assert job["attempts"] == 1
        assert job["error"]
        response = await client.post("/api/v1/kitchen/generation-jobs/2026-09-21/retry")
        assert response.status_code == 200
        assert response.json()["job"]["status"] == "pending"
        assert response.json()["job"]["attempts"] == 0
        other = HouseholdScope(uuid4(), uuid4())
        app.dependency_overrides[get_household_scope] = lambda: other
        assert (await client.get("/api/v1/kitchen/generation-jobs")).json() == {"jobs": []}
        assert (
            await client.post("/api/v1/kitchen/generation-jobs/2026-09-21/retry")
        ).status_code == 404
