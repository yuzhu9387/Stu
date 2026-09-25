"""Backfill fidelity: the relational rows must agree with the JSON aggregate.

Uses the throwaway PostgreSQL database configured by
`RECIPE_AGENT_TEST_DATABASE_URL`; skipped when it is absent, like the other
PostgreSQL integration tests.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from recipe_agent.domain.kitchen import schema as s
from recipe_agent.domain.kitchen.backfill import backfill_household

DATABASE_URL = os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="RECIPE_AGENT_TEST_DATABASE_URL is not configured"
)


def workspace() -> dict:
    """A household exercising every edge the backfill has to preserve."""
    return {
        "revision": 12,
        "tags": ["Protein", "批量备餐"],
        "settings": {
            "people": 3,
            "childAge": 24.0,
            "allergies": ["花生"],
            "timezone": "America/Los_Angeles",
            "generateTime": "17:00",
            "prepDay": 6,
            "maxPrepMinutes": 240.0,
            "maxDailyActiveMinutes": 30.0,
            "newRecipesPerWeek": 2,
            "recipeRepeatGapDays": 1,
            "guidance": [
                {
                    "id": "g-family",
                    "title": "Family basics",
                    "content": "一家三口",
                    "enabled": True,
                    "version": 1,
                }
            ],
        },
        "knowledgeDocuments": [
            {
                "id": "k-1",
                "title": "膳食指南",
                "category": "Nutrition",
                "content": "多吃蔬菜",
                "enabled": True,
                "version": 1,
                "updatedAt": "2026-09-13T00:00:00+00:00",
            }
        ],
        "recipes": [
            {
                "id": "r-meatball",
                "name": "鸡肉丸",
                "type": "Protein",
                "mealTypes": ["lunch", "dinner"],
                # 冷冻友好 is deliberately absent from state["tags"], as tag.apply
                # can introduce a tag that the global list never saw.
                "tags": ["Protein", "批量备餐", "冷冻友好"],
                "servings": 6.0,
                "activeMinutes": 35.0,
                "elapsedMinutes": 55.0,
                "ingredients": [
                    {"name": "鸡腿肉", "quantity": 500.0, "unit": "g"},
                    {"name": "鸡蛋", "quantity": 1.0, "unit": "个"},
                ],
                "steps": ["绞肉", "煎熟"],
                "liked": True,
                "source": "手动录入",
                "incomplete": False,
                "allergens": ["蛋"],
                "equipment": ["skillet"],
            }
        ],
        "inventory": [
            {
                "id": "inv-eggs",
                "name": "鸡蛋",
                "type": "Protein",
                "portions": 10.0,
                "location": "fridge",
                "prepared": False,
                "addedOn": "2026-09-12",
                "priority": False,
            },
            {
                "id": "inv-a-meatball",
                "name": "鸡肉丸",
                "type": "Protein",
                "portions": 6.0,
                "location": "fridge",
                "prepared": True,
                "addedOn": "2026-09-13",
                "recipeId": "r-meatball",
                "priority": False,
            },
        ],
        "plans": [
            {
                "id": "plan-1",
                "weekStart": "2026-09-14",
                "status": "confirmed",
                "version": 3,
                "prompt": "用掉冰箱里的菠菜",
                "meals": [
                    {
                        "id": "m-mon-lunch",
                        "day": "2026-09-14",
                        "slot": "lunch",
                        "components": [
                            {
                                "id": "c1",
                                "name": "鸡肉丸",
                                "type": "Protein",
                                "portions": 3.0,
                                "recipeId": "r-meatball",
                                "prepId": "prep-1",
                            }
                        ],
                        "activeMinutes": 8.0,
                        "elapsedMinutes": 12.0,
                        "steps": ["复热 6 分钟"],
                        "status": "completed",
                        "liked": True,
                        "locked": False,
                    }
                ],
                "prep": [
                    {
                        "id": "prep-1",
                        "name": "鸡肉丸",
                        "type": "Protein",
                        "recipeId": "r-meatball",
                        "plannedPortions": 12.0,
                        "actualPortions": 9.0,
                        "activeMinutes": 70.0,
                        "elapsedMinutes": 110.0,
                        "steps": ["绞两批肉糜"],
                        "status": "completed",
                        "liked": False,
                        "outputInventoryId": "inv-a-meatball",
                        "inputs": [{"inventoryId": "inv-eggs", "portions": 2.0}],
                        "equipment": ["skillet"],
                        "dependencies": [],
                    }
                ],
                "chat": [
                    {
                        "id": "chat-1",
                        "role": "user",
                        "text": "换个不用开火的",
                        "mealIds": ["m-mon-lunch"],
                    }
                ],
                "guidanceSnapshot": [
                    {
                        "id": "g-family",
                        "title": "Family basics",
                        "content": "一家三口",
                        "enabled": True,
                        "version": 1,
                    }
                ],
                "knowledgeSnapshot": [],
            }
        ],
        "weeklyPrompts": [{"weekStart": "2026-09-21", "prompt": "少做点"}],
        "audit": [
            {
                "id": "a-1",
                "kind": "prep.status",
                "message": "Changes saved",
                "at": "2026-09-13T10:00:00+00:00",
                "deltas": [
                    {"inventoryId": "inv-a-meatball", "amount": 9.0},
                    {"inventoryId": "inv-eggs", "amount": -2.0},
                ],
                "undone": False,
                "planId": "plan-1",
            },
            {
                "id": "a-2",
                "kind": "meal.status",
                "message": "Changes saved",
                "at": "2026-09-14T12:00:00+00:00",
                "deltas": [{"inventoryId": "inv-a-meatball", "amount": -3.0}],
                "undone": False,
                "planId": "plan-1",
            },
        ],
    }


async def test_backfill_preserves_every_record(relational_sessions, relational_household):
    state = workspace()
    async with relational_sessions() as session, session.begin():
        report = await backfill_household(session, relational_household, state)

    assert report.counts["kitchen_recipes"] == 1
    assert report.counts["inventory_batches"] == 2
    assert report.counts["weekly_plans"] == 1
    assert report.counts["meals"] == 1
    assert report.counts["prep_tasks"] == 1

    async with relational_sessions() as session:
        # Legacy transport ids survive, so existing frontend URLs keep resolving.
        recipe = await session.scalar(
            select(s.KitchenRecipe).where(s.KitchenRecipe.legacy_id == "r-meatball")
        )
        assert recipe is not None
        assert recipe.name == "鸡肉丸"
        assert recipe.category == s.FoodCategory.PROTEIN
        assert recipe.is_favorite is True
        assert recipe.servings == Decimal("6.00")

        # 鸡蛋 appears as a recipe ingredient and as a fridge batch: one row.
        eggs = (
            await session.scalars(
                select(s.FoodItem).where(
                    s.FoodItem.household_id == relational_household, s.FoodItem.name == "鸡蛋"
                )
            )
        ).all()
        assert len(eggs) == 1
        # The fridge batch supplies the real category; the ingredient alone
        # would only have said "other".
        assert eggs[0].category == s.FoodCategory.PROTEIN

        steps = (
            await session.scalars(
                select(s.RecipeStep.body)
                .where(s.RecipeStep.recipe_id == recipe.id)
                .order_by(s.RecipeStep.position)
            )
        ).all()
        assert list(steps) == ["绞肉", "煎熟"]

        allergens = (
            await session.scalars(
                select(s.RecipeAllergen.label).where(s.RecipeAllergen.recipe_id == recipe.id)
            )
        ).all()
        assert list(allergens) == ["蛋"]

        meal = await session.scalar(
            select(s.Meal).where(s.Meal.legacy_id == "m-mon-lunch")
        )
        assert meal is not None
        assert meal.status == s.ExecutionStatus.COMPLETED
        assert meal.liked is True
        assert meal.included is True

        component = await session.scalar(
            select(s.MealComponent).where(s.MealComponent.meal_id == meal.id)
        )
        assert component is not None
        assert component.recipe_id == recipe.id
        assert component.prep_task_id is not None

        prep = await session.scalar(select(s.PrepTask).where(s.PrepTask.legacy_id == "prep-1"))
        assert prep is not None
        assert prep.actual_portions == Decimal("9.00")
        assert prep.output_batch_id is not None

        settings = await session.get(s.HouseholdKitchenSettings, relational_household)
        assert settings is not None
        assert settings.child_age_months == Decimal("24.00")
        assert settings.timezone == "America/Los_Angeles"

        allergy = await session.scalar(
            select(s.HouseholdAllergy.label).where(
                s.HouseholdAllergy.household_id == relational_household
            )
        )
        assert allergy == "花生"

        reference = await session.scalar(select(func.count()).select_from(s.PlanChatReference))
        assert reference == 1

        snapshot = await session.scalar(
            select(func.count()).select_from(s.PlanGuidanceSnapshot)
        )
        assert snapshot == 1


async def test_ledger_sums_to_the_aggregate_balance(relational_sessions, relational_household):
    """The invariant the aggregate could not enforce: balance == sum(ledger)."""
    state = workspace()
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)

    expected = {item["id"]: Decimal(str(item["portions"])) for item in state["inventory"]}
    async with relational_sessions() as session:
        for legacy_id, portions in expected.items():
            batch = await session.scalar(
                select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == legacy_id)
            )
            assert batch is not None
            total = await session.scalar(
                select(func.coalesce(func.sum(s.InventoryLedgerEntry.delta), 0)).where(
                    s.InventoryLedgerEntry.batch_id == batch.id
                )
            )
            assert Decimal(str(total)) == portions, legacy_id

        # Historical movements are replayed, not collapsed into one opening row.
        meatball = await session.scalar(
            select(s.InventoryBatch).where(s.InventoryBatch.legacy_id == "inv-a-meatball")
        )
        assert meatball is not None
        reasons = (
            await session.scalars(
                select(s.InventoryLedgerEntry.reason)
                .where(s.InventoryLedgerEntry.batch_id == meatball.id)
                .order_by(s.InventoryLedgerEntry.created_at)
            )
        ).all()
        assert s.LedgerReason.PREP_OUTPUT in reasons
        assert s.LedgerReason.MEAL_CONSUMPTION in reasons


async def test_backfill_is_idempotent(relational_sessions, relational_household):
    state = workspace()
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)
    async with relational_sessions() as session, session.begin():
        await backfill_household(session, relational_household, state)

    async with relational_sessions() as session:
        for model in (s.KitchenRecipe, s.InventoryBatch, s.WeeklyPlan, s.Meal, s.PrepTask):
            count = await session.scalar(select(func.count()).select_from(model))
            assert count == (2 if model is s.InventoryBatch else 1), model.__name__
        foods = await session.scalar(select(func.count()).select_from(s.FoodItem))
        assert foods == 3  # 鸡腿肉, 鸡蛋, 鸡肉丸
        tags = await session.scalar(select(func.count()).select_from(s.Tag))
        assert tags == 3  # Protein, 批量备餐, 冷冻友好
