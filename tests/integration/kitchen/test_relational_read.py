"""The relational read path must reproduce the JSON aggregate exactly.

This is the gate for the storage cutover: the frontend, engine, MCP endpoint and
AI generation all consume the `Workspace` contract, so the tables are only ready
to replace `kitchen_workspaces` once the two render identically.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from recipe_agent.domain.kitchen import schema as s
from recipe_agent.domain.kitchen.backfill import backfill_household
from recipe_agent.domain.kitchen.contracts import Workspace
from recipe_agent.domain.kitchen.relational_read import RelationalWorkspaceReader

from .test_backfill import workspace

DATABASE_URL = os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="RECIPE_AGENT_TEST_DATABASE_URL is not configured"
)


def canonical(document: dict[str, Any]) -> dict[str, Any]:
    """Sort the collections whose array order was an aggregate artifact.

    Audit order, prep order and component order are deliberately left alone:
    undo walks the audit forward, and the scheduler's tie-break preserves the
    author's prep and component order.
    """
    out = dict(document)
    for key in ("recipes", "inventory", "plans", "knowledgeDocuments"):
        out[key] = sorted(out.get(key, []), key=lambda row: row["id"])
    for plan in out["plans"]:
        plan["meals"] = sorted(plan["meals"], key=lambda row: row["id"])
        plan["guidanceSnapshot"] = sorted(plan["guidanceSnapshot"], key=lambda r: r["id"])
        plan["knowledgeSnapshot"] = sorted(plan["knowledgeSnapshot"], key=lambda r: r["id"])
    out["settings"] = dict(out["settings"])
    out["settings"]["guidance"] = sorted(out["settings"]["guidance"], key=lambda r: r["id"])
    out["settings"]["allergies"] = sorted(out["settings"]["allergies"])
    out["tags"] = sorted(out["tags"])
    return out


async def test_relational_read_matches_the_aggregate(relational_sessions, relational_household):
    state = workspace()
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)

    aggregate = Workspace.model_validate(state).model_dump(mode="json", exclude_none=True)
    async with relational_sessions() as session:
        raw = await RelationalWorkspaceReader(session).load(relational_household, state["revision"])

    # It must satisfy the same contract the API already serves.
    rebuilt = Workspace.model_validate(raw).model_dump(mode="json", exclude_none=True)
    assert canonical(rebuilt) == canonical(aggregate)


async def test_portions_come_from_the_ledger(relational_sessions, relational_household):
    """Balances are derived, so a new movement changes the rendered workspace."""
    state = workspace()
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)

    async with relational_sessions() as session, session.begin():
        batch = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-eggs")
        )
        assert batch is not None
        session.add(
            s.InventoryLedgerEntry(
                id=uuid4(),
                household_id=relational_household,
                batch_id=batch.id,
                delta=Decimal("-4"),
                reason=s.LedgerReason.MANUAL_ADJUST,
            )
        )

    async with relational_sessions() as session:
        raw = await RelationalWorkspaceReader(session).load(relational_household, state["revision"])
    eggs = next(item for item in raw["inventory"] if item["id"] == "inv-eggs")
    assert eggs["portions"] == 6.0  # 10 from the aggregate, minus the new entry


async def test_unlisted_recipe_tag_stays_out_of_the_catalog(
    relational_sessions, relational_household
):
    """`冷冻友好` reaches a recipe via tag.apply without joining state["tags"]."""
    state = workspace()
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)

    async with relational_sessions() as session:
        raw = await RelationalWorkspaceReader(session).load(relational_household, state["revision"])
    assert sorted(raw["tags"]) == sorted(state["tags"])
    recipe = next(item for item in raw["recipes"] if item["id"] == "r-meatball")
    assert "冷冻友好" in recipe["tags"]


async def test_falls_back_to_the_aggregate_when_never_backfilled(
    relational_sessions, relational_scope
):
    """Turning the flag on must not serve an empty workspace.

    A household can have an aggregate row while its tables are still empty —
    it existed before the cutover and nobody ran the backfill. Serving the
    aggregate is always safe; serving nothing is not.
    """
    from recipe_agent.domain.kitchen.models import KitchenWorkspace
    from recipe_agent.domain.kitchen.repository import KitchenRepository

    state = workspace()
    async with relational_sessions() as session, session.begin():
        session.add(
            KitchenWorkspace(
                household_id=relational_scope.household_id,
                revision=state["revision"],
                state=state,
            )
        )

    served = await KitchenRepository(relational_sessions, relational_read=True).get(
        relational_scope
    )
    assert len(served["recipes"]) == len(state["recipes"])
    assert len(served["plans"]) == len(state["plans"])
    assert len(served["inventory"]) == len(state["inventory"])


async def test_ordered_collections_keep_their_array_order(relational_sessions, relational_scope):
    """Recipes, fridge batches and plans are arrays the UI renders in order.

    Rows written in one loop share a `created_at` to the microsecond, so
    ordering by timestamp alone falls back to a random UUID and the list
    silently reshuffles between reads.
    """
    state = workspace()
    # Enough rows that a timestamp tie is certain.
    state["inventory"] = [
        {**state["inventory"][0], "id": f"inv-{index}", "name": f"食材{index}"}
        for index in range(12)
    ]
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_scope.household_id, state)

    expected = [item["id"] for item in state["inventory"]]
    async with relational_sessions() as session:
        for _ in range(3):
            rebuilt = await RelationalWorkspaceReader(session).load(
                relational_scope.household_id, state["revision"]
            )
            assert [item["id"] for item in rebuilt["inventory"]] == expected


async def test_confirmation_snapshot_and_weekly_rules_round_trip(
    relational_sessions, relational_household
):
    from recipe_agent.domain.kitchen.fulfillment import inputs_hash

    state = workspace()
    plan = state["plans"][0]
    state["settings"]["recurringMeals"] = [
        {"weekday": 0, "slot": "breakfast", "meal": plan["meals"][0], "prep": plan["prep"]}
    ]
    plan["fulfillment"] = {
        "stale": False,
        "recipeHashes": {"recipe": "verified-hash"},
        "batchRecipes": ["recipe"],
        "prepNotes": {},
        "shopping": [
            {
                "name": "Rice",
                "unit": "g",
                "group": "Carbs",
                "required": 300,
                "inStock": 100,
                "toBuy": 200,
                "dishes": ["Rice"],
            }
        ],
        "warnings": [],
        "generatedAt": "2026-09-24T12:00:00+00:00",
        "source": "ai",
    }
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)
    async with relational_sessions() as session:
        rebuilt = await RelationalWorkspaceReader(session).load(
            relational_household, state["revision"]
        )
    rebuilt = Workspace.model_validate(rebuilt).model_dump(mode="json", exclude_none=True)
    assert rebuilt["plans"][0]["fulfillment"] == plan["fulfillment"]
    assert (
        rebuilt["settings"]["recurringMeals"]
        == Workspace.model_validate(state).model_dump(mode="json", exclude_none=True)["settings"][
            "recurringMeals"
        ]
    )
    assert inputs_hash(state, plan) == inputs_hash(rebuilt, rebuilt["plans"][0])


async def test_confirmation_fingerprint_for_linked_recipe_and_prep(
    relational_sessions, relational_scope
):
    from recipe_agent.domain.kitchen.fulfillment import inputs_hash
    from tests.unit.kitchen.test_ai_scheduling_mcp import recipe
    from tests.unit.kitchen.test_engine import fixture_state

    state = fixture_state()
    state["recipes"] = [{**recipe(), "mealTypes": ["lunch", "dinner"]}]
    state["inventory"][0]["recipeId"] = "rice"
    state["plans"][0]["prep"][0]["recipeId"] = "rice"
    state["plans"][0]["meals"][0]["components"][0].update(recipeId="rice", prepId="prep")
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_scope.household_id, state)
    async with relational_sessions() as session:
        rebuilt = await RelationalWorkspaceReader(session).load(
            relational_scope.household_id, state["revision"]
        )
    rebuilt = Workspace.model_validate(rebuilt).model_dump(mode="json", exclude_none=True)
    expected = Workspace.model_validate(state).model_dump(mode="json", exclude_none=True)

    def diff(a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            return [
                d for k in a.keys() | b.keys() for d in diff(a.get(k), b.get(k), path + "." + k)
            ]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            if a and all(isinstance(x, dict) and "id" in x for x in a + b):
                a = sorted(a, key=lambda x: x["id"])
                b = sorted(b, key=lambda x: x["id"])
            return [
                d
                for i, (x, y) in enumerate(zip(a, b, strict=True))
                for d in diff(x, y, path + str(i))
            ]
        return [(path, a, b)] if a != b else []

    assert inputs_hash(expected, expected["plans"][0]) == inputs_hash(
        rebuilt, rebuilt["plans"][0]
    ), diff(expected, rebuilt)


async def test_confirmation_fingerprint_after_live_commands(relational_sessions, relational_scope):
    from recipe_agent.domain.kitchen.fulfillment import inputs_hash
    from recipe_agent.domain.kitchen.repository import KitchenRepository
    from tests.unit.kitchen.test_ai_scheduling_mcp import recipe
    from tests.unit.kitchen.test_engine import fixture_state

    repo = KitchenRepository(relational_sessions, relational_read=True)
    state = await repo.get(relational_scope)

    async def command(kind, payload):
        nonlocal state
        state = (
            await repo.command(
                relational_scope,
                {
                    "type": kind,
                    "payload": payload,
                    "expectedRevision": state["revision"],
                    "operationId": str(uuid4()),
                },
            )
        )["state"]

    r = {
        **recipe(),
        "id": "chicken",
        "name": "鸡肉丸",
        "type": "Protein",
        "mealTypes": ["lunch", "dinner"],
        "servings": 3,
        "activeMinutes": 8,
        "elapsedMinutes": 18,
        "ingredients": [{"name": "鸡肉", "quantity": 300, "unit": "g"}],
        "steps": ["Prepare chicken", "Cook through and portion"],
        "source": "Explicit E2E test fixture",
    }
    await command("recipe.save", {"recipe": r})
    inventory = [
        {"id": "meat", "name": "鸡肉丸", "type": "Protein", "portions": 2, "recipeId": "chicken"},
        {"id": "rice", "name": "糙米饭", "type": "Carbs", "portions": 6},
        {"id": "veg", "name": "西兰花", "type": "Vegetables", "portions": 4},
    ]
    for i in inventory:
        await command(
            "inventory.save",
            {
                "item": {
                    **i,
                    "location": "Freezer",
                    "prepared": True,
                    "addedOn": "2026-09-17",
                    "priority": False,
                }
            },
        )
    p = fixture_state()["plans"][0]
    p.update(id="week", status="draft", weekStart="2026-09-21")
    p["meals"][0].update(
        id="dinner",
        day="2026-09-23",
        components=[
            {
                "id": i["id"],
                "name": i["name"],
                "type": i["type"],
                "portions": 3,
                "inventoryId": i["id"],
                **({"recipeId": "chicken", "prepId": "prep"} if i["id"] == "meat" else {}),
            }
            for i in inventory
        ],
    )
    p["prep"][0].update(
        name="鸡肉丸",
        type="Protein",
        recipeId="chicken",
        outputInventoryId="meat",
        equipment=["stove"],
    )
    await command("plan.save", {"plan": p})
    rebuilt = await repo.get(relational_scope)

    def diff(a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            return [
                d for k in a.keys() | b.keys() for d in diff(a.get(k), b.get(k), path + "." + k)
            ]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            if a and all(isinstance(x, dict) and "id" in x for x in a + b):
                a = sorted(a, key=lambda x: x["id"])
                b = sorted(b, key=lambda x: x["id"])
            return [
                d
                for i, (x, y) in enumerate(zip(a, b, strict=True))
                for d in diff(x, y, path + str(i))
            ]
        return [(path, a, b)] if a != b else []

    assert inputs_hash(state, state["plans"][0]) == inputs_hash(rebuilt, rebuilt["plans"][0]), diff(
        state, rebuilt
    )
