"""Phase B group 2: fridge batches, the stock ledger and the audit trail.

The invariant the JSON aggregate could not enforce is that a batch's portions
equal the sum of its movements. These tests assert it after every command, not
only after a backfill.
"""

from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from recipe_agent.domain.kitchen import schema as s

from .test_relational_write import Driver, recipe

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL"),
    reason="RECIPE_AGENT_TEST_DATABASE_URL is not configured",
)

WEEK = "2026-09-14"


def batch(identifier: str, name: str, portions: float, **overrides):
    base = {
        "id": identifier,
        "name": name,
        "type": "Protein",
        "portions": portions,
        "location": "fridge",
        "prepared": False,
        "addedOn": "2026-09-12",
        "priority": False,
    }
    return {**base, **overrides}


def plan_with_prep():
    """One prep task feeding one meal: the smallest complete execution loop."""
    return {
        "id": "p-1",
        "weekStart": WEEK,
        "status": "draft",
        "version": 1,
        "prompt": "",
        "meals": [
            {
                "id": "m-1",
                "day": WEEK,
                "slot": "dinner",
                "components": [
                    {
                        "id": "m-1-c1",
                        "name": "鸡肉丸",
                        "type": "Protein",
                        "portions": 2.0,
                        "recipeId": "r-1",
                        "prepId": "prep-1",
                    }
                ],
                "activeMinutes": 5.0,
                "elapsedMinutes": 10.0,
                "steps": ["复热"],
                "status": "planned",
                "liked": False,
                "locked": False,
            }
        ],
        "prep": [
            {
                "id": "prep-1",
                "name": "鸡肉丸",
                "type": "Protein",
                "recipeId": "r-1",
                "plannedPortions": 4.0,
                "actualPortions": 0.0,
                "activeMinutes": 10.0,
                "elapsedMinutes": 20.0,
                "steps": ["绞肉", "煎熟"],
                "status": "planned",
                "liked": False,
                "outputInventoryId": "inv-out",
                "inputs": [{"inventoryId": "inv-eggs", "portions": 2.0}],
                "equipment": ["skillet"],
                "dependencies": [],
            }
        ],
        "chat": [],
    }


@pytest.fixture
def driver(relational_sessions, relational_scope):
    return Driver(relational_sessions, relational_scope)


async def assert_ledger_matches(sessions, state) -> None:
    """portions == sum(ledger), for every batch, no exceptions."""
    async with sessions() as session:
        for item in state["inventory"]:
            row = await session.scalar(
                select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == item["id"])
            )
            assert row is not None, f"missing batch {item['id']}"
            total = await session.scalar(
                select(func.coalesce(func.sum(s.InventoryLedgerEntry.delta), 0)).where(
                    s.InventoryLedgerEntry.batch_id == row.id
                )
            )
            assert Decimal(str(total)) == Decimal(str(item["portions"])), item["id"]
        count = await session.scalar(select(func.count()).select_from(s.InventoryBatch))
        assert count == len(state["inventory"])


async def test_inventory_save_creates_a_batch_with_an_opening_entry(driver, relational_sessions):
    state = await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    await assert_ledger_matches(relational_sessions, state)

    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-eggs")
        )
        entries = (
            await session.scalars(
                select(s.InventoryLedgerEntry).where(s.InventoryLedgerEntry.batch_id == row.id)
            )
        ).all()
        assert len(entries) == 1
        assert entries[0].delta == Decimal("10")
        assert entries[0].reason == s.LedgerReason.MANUAL_ADJUST


async def test_editing_portions_appends_a_correction_rather_than_overwriting(
    driver, relational_sessions
):
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    state = await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 6.0)})
    await assert_ledger_matches(relational_sessions, state)

    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-eggs")
        )
        deltas = sorted(
            (
                await session.scalars(
                    select(s.InventoryLedgerEntry.delta).where(
                        s.InventoryLedgerEntry.batch_id == row.id
                    )
                )
            ).all()
        )
        # History is preserved: +10 then -4, not a single rewritten 6.
        assert [Decimal(str(d)) for d in deltas] == [Decimal("-4"), Decimal("10")]


async def test_inventory_delete_removes_the_batch_and_its_ledger(driver, relational_sessions):
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    await driver.send("inventory.delete", {"id": "inv-eggs"})
    async with relational_sessions() as session:
        assert (await session.scalar(select(func.count()).select_from(s.InventoryBatch))) == 0
        assert (await session.scalar(select(func.count()).select_from(s.InventoryLedgerEntry))) == 0


async def test_execution_loop_keeps_the_ledger_true_at_every_step(driver, relational_sessions):
    await driver.send(
        "recipe.save",
        {
            "recipe": recipe(
                "r-1",
                "鸡肉丸",
                servings=4.0,
                activeMinutes=10.0,
                elapsedMinutes=20.0,
                mealTypes=["dinner"],
                equipment=["skillet"],
            )
        },
    )
    state = await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    await assert_ledger_matches(relational_sessions, state)

    await driver.send("plan.save", {"plan": plan_with_prep()})
    state = await driver.send("plan.confirm", {"id": "p-1"})
    # Confirming reserves supply but must not move any stock.
    await assert_ledger_matches(relational_sessions, state)
    assert next(i for i in state["inventory"] if i["id"] == "inv-eggs")["portions"] == 10.0

    state = await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    await assert_ledger_matches(relational_sessions, state)
    portions = {i["id"]: i["portions"] for i in state["inventory"]}
    assert portions["inv-eggs"] == 8.0  # two eggs consumed as an input
    assert portions["inv-out"] == 4.0  # four portions produced

    async with relational_sessions() as session:
        out = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-out")
        )
        reasons = (
            await session.scalars(
                select(s.InventoryLedgerEntry.reason).where(
                    s.InventoryLedgerEntry.batch_id == out.id
                )
            )
        ).all()
        assert s.LedgerReason.PREP_OUTPUT in reasons

    state = await driver.send(
        "meal.status", {"planId": "p-1", "mealId": "m-1", "status": "completed"}
    )
    await assert_ledger_matches(relational_sessions, state)
    assert next(i for i in state["inventory"] if i["id"] == "inv-out")["portions"] == 2.0

    async with relational_sessions() as session:
        out = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-out")
        )
        reasons = (
            await session.scalars(
                select(s.InventoryLedgerEntry.reason).where(
                    s.InventoryLedgerEntry.batch_id == out.id
                )
            )
        ).all()
        assert s.LedgerReason.MEAL_CONSUMPTION in reasons

    aggregate, relational = await driver.both()
    assert relational["inventory"] == aggregate["inventory"]


async def test_undo_writes_a_compensating_entry_and_restores_the_balance(
    driver, relational_sessions
):
    await driver.send(
        "recipe.save",
        {
            "recipe": recipe(
                "r-1",
                "鸡肉丸",
                servings=4.0,
                activeMinutes=10.0,
                elapsedMinutes=20.0,
                mealTypes=["dinner"],
                equipment=["skillet"],
            )
        },
    )
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await driver.send("plan.confirm", {"id": "p-1"})
    await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    state = await driver.send(
        "meal.status", {"planId": "p-1", "mealId": "m-1", "status": "completed"}
    )
    audit_id = state["audit"][-1]["id"]

    async with relational_sessions() as session:
        before = await session.scalar(select(func.count()).select_from(s.InventoryLedgerEntry))

    state = await driver.send("change.undo", {"auditId": audit_id})
    await assert_ledger_matches(relational_sessions, state)
    assert next(i for i in state["inventory"] if i["id"] == "inv-out")["portions"] == 4.0

    async with relational_sessions() as session:
        after = await session.scalar(select(func.count()).select_from(s.InventoryLedgerEntry))
        # The original consumption row stays; undo appends its inverse.
        assert after > before
        reversal = await session.scalar(
            select(func.count())
            .select_from(s.InventoryLedgerEntry)
            .where(s.InventoryLedgerEntry.reason == s.LedgerReason.UNDO_REVERSAL)
        )
        assert reversal >= 1
        undone = await session.scalar(
            select(s.KitchenAuditEntry).where(s.KitchenAuditEntry.legacy_id == audit_id)
        )
        assert undone is not None and undone.undone is True


async def test_audit_trail_is_appended_with_order_and_deltas(driver, relational_sessions):
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    state = await driver.send("inventory.save", {"item": batch("inv-milk", "牛奶", 3.0)})

    async with relational_sessions() as session:
        rows = (
            await session.scalars(
                select(s.KitchenAuditEntry).order_by(s.KitchenAuditEntry.sequence)
            )
        ).all()
        assert [row.sequence for row in rows] == list(range(len(state["audit"])))
        assert [row.legacy_id for row in rows] == [a["id"] for a in state["audit"]]

    aggregate, relational = await driver.both()
    assert relational["audit"] == aggregate["audit"]


async def test_rejected_command_rolls_back_the_ledger_too(driver, relational_sessions):
    state = await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    async with relational_sessions() as session:
        before = await session.scalar(select(func.count()).select_from(s.InventoryLedgerEntry))

    from recipe_agent.domain.kitchen.engine import KitchenError

    with pytest.raises(KitchenError):
        await driver.repo.command(
            driver.scope,
            {
                "type": "inventory.save",
                "payload": {"item": batch("inv-milk", "牛奶", 3.0)},
                "expectedRevision": 999,
                "operationId": uuid4().hex,
            },
        )
    async with relational_sessions() as session:
        after = await session.scalar(select(func.count()).select_from(s.InventoryLedgerEntry))
    assert after == before
    await assert_ledger_matches(relational_sessions, state)


async def test_fridge_fields_from_frame_110_5_round_trip(driver, relational_sessions):
    """Expiry, notes, per-portion weight, emoji, English name and Dairy."""
    state = await driver.send(
        "inventory.save",
        {
            "item": batch(
                "inv-milk",
                "牛奶",
                3.0,
                type="Dairy",
                expiresOn="2026-09-27",
                notes="周日 batch cook 做的",
                portionGrams=250.0,
                emoji="🥛",
                nameEn="Milk",
            )
        },
    )
    item = next(i for i in state["inventory"] if i["id"] == "inv-milk")
    assert item["type"] == "Dairy"
    assert item["expiresOn"] == "2026-09-27"
    assert item["portionGrams"] == 250.0

    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-milk")
        )
        assert row.expires_on.isoformat() == "2026-09-27"
        assert row.notes == "周日 batch cook 做的"
        food = await session.get(s.FoodItem, row.food_item_id)
        assert food.category == s.FoodCategory.DAIRY
        assert food.emoji == "🥛"
        assert food.name_en == "Milk"

    aggregate, relational = await driver.both()
    assert relational["inventory"] == aggregate["inventory"]


async def test_emoji_is_shared_by_every_batch_of_the_same_food(driver):
    """One food record, so re-iconing it reaches each batch at once."""
    await driver.send("inventory.save", {"item": batch("inv-a", "鸡蛋", 6.0)})
    await driver.send("inventory.save", {"item": batch("inv-b", "鸡蛋", 4.0)})
    state = await driver.send("inventory.save", {"item": batch("inv-a", "鸡蛋", 6.0, emoji="🥚")})
    icons = {i["id"]: i.get("emoji") for i in state["inventory"]}
    assert icons == {"inv-a": "🥚", "inv-b": "🥚"}


async def test_absent_fridge_fields_stay_absent(driver):
    """No invented expiry or weight; an unknown value is simply not reported."""
    state = await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    item = next(i for i in state["inventory"] if i["id"] == "inv-eggs")
    for key in ("expiresOn", "notes", "portionGrams", "emoji", "nameEn"):
        assert key not in item, key


async def test_clearing_a_shared_food_attribute_round_trips(driver):
    """Set an icon, then save without it: both paths must agree afterwards.

    The food record is derived from its batches, so an attribute the aggregate
    no longer carries cannot linger in the tables.
    """
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0, emoji="🥚")})
    aggregate, relational = await driver.both()
    assert relational["inventory"] == aggregate["inventory"]

    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    aggregate, relational = await driver.both()
    assert relational["inventory"] == aggregate["inventory"]
    assert "emoji" not in aggregate["inventory"][0]


async def test_undoing_prep_done_removes_the_box_it_made(driver, relational_sessions):
    await driver.send(
        "recipe.save",
        {
            "recipe": recipe(
                "r-1",
                "鸡肉丸",
                servings=4.0,
                activeMinutes=10.0,
                elapsedMinutes=20.0,
                mealTypes=["dinner"],
                equipment=["skillet"],
            )
        },
    )
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    plan = plan_with_prep()
    plan["prep"][0].pop("outputInventoryId", None)
    await driver.send("plan.save", {"plan": plan})
    await driver.send("plan.confirm", {"id": "p-1"})
    state = await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    box = next(i for i in state["inventory"] if i["id"] == "prep-prep-1")
    assert box["location"] == "freezer"

    state = await driver.send("change.undo", {"auditId": state["audit"][-1]["id"]})
    assert "prep-prep-1" not in {i["id"] for i in state["inventory"]}
    await assert_ledger_matches(relational_sessions, state)
    aggregate, relational = await driver.both()
    assert relational["inventory"] == aggregate["inventory"]
    assert relational["plans"][0]["prep"][0]["status"] == "planned"
    assert "outputInventoryId" not in relational["plans"][0]["prep"][0]


async def test_a_box_used_by_finished_meals_and_prep_can_be_taken_out(driver, relational_sessions):
    await driver.send(
        "recipe.save",
        {
            "recipe": recipe(
                "r-1",
                "鸡肉丸",
                servings=4.0,
                activeMinutes=10.0,
                elapsedMinutes=20.0,
                mealTypes=["dinner"],
                equipment=["skillet"],
            )
        },
    )
    await driver.send("inventory.save", {"item": batch("inv-eggs", "鸡蛋", 10.0)})
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await driver.send("plan.confirm", {"id": "p-1"})
    await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    await driver.send("meal.status", {"planId": "p-1", "mealId": "m-1", "status": "completed"})

    # The eggs went into finished prep; the meatballs into a finished meal.
    await driver.send("inventory.delete", {"id": "inv-eggs"})
    state = await driver.send("inventory.delete", {"id": "inv-out"})
    assert {i["id"] for i in state["inventory"]} == set()
    task = state["plans"][0]["prep"][0]
    assert task["status"] == "completed" and task["inputs"] == []
    assert "outputInventoryId" not in task
    await assert_ledger_matches(relational_sessions, state)
    aggregate, relational = await driver.both()
    assert relational["inventory"] == aggregate["inventory"] == []
    assert relational["plans"] == aggregate["plans"]
