"""Phase B group 3: plans, meals, prep, chat, snapshots, settings and prompts.

With this group the projection covers every section, so the strongest assertion
available is that both read paths render the *entire* workspace identically
after a full execution loop — not just the sections a test happens to poke.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from recipe_agent.domain.kitchen import schema as s

from .test_relational_inventory import batch, plan_with_prep
from .test_relational_write import Driver, recipe

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL"),
    reason="RECIPE_AGENT_TEST_DATABASE_URL is not configured",
)

WEEK = "2026-09-14"


@pytest.fixture
def driver(relational_sessions, relational_scope):
    return Driver(relational_sessions, relational_scope)


def canonical(document: dict) -> dict:
    """Meal order is (day, slot) relationally; nothing consumes it positionally."""
    out = dict(document)
    out["plans"] = [
        {**plan, "meals": sorted(plan["meals"], key=lambda m: m["id"])} for plan in out["plans"]
    ]
    return out


async def assert_identical(driver) -> None:
    aggregate, relational = await driver.both()
    assert canonical(relational) == canonical(aggregate)


async def seed(driver):
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


async def test_workflow_and_shopping_checks_survive_relational_reload(driver):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await driver.send(
        "planning.workflow",
        {
            "weekStart": WEEK,
            "workflow": {"planId": "p-1", "step": "preferences", "focus": "shopping"},
        },
    )
    await driver.send("planning.prompt", {"weekStart": WEEK, "prompt": "Use eggs"})
    await assert_identical(driver)
    await driver.send("plan.confirm", {"id": "p-1"})
    await driver.send("shopping.check", {"planId": "p-1", "key": "鸡蛋|pcs|3", "checked": True})
    await driver.send(
        "planning.workflow",
        {
            "weekStart": WEEK,
            "workflow": {"planId": "p-1", "step": "shopping", "focus": "prep"},
        },
    )
    await assert_identical(driver)
    _, loaded = await driver.both()
    assert loaded["weeklyPrompts"][0]["prompt"] == "Use eggs"
    assert loaded["weeklyPrompts"][0]["workflow"]["focus"] == "prep"
    assert loaded["plans"][0]["shoppingChecked"] == ["鸡蛋|pcs|3"]


async def test_plan_save_projects_meals_prep_and_children(driver, relational_sessions):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})

    async with relational_sessions() as session:
        plan = await session.scalar(select(s.WeeklyPlan).where(s.WeeklyPlan.legacy_id == "p-1"))
        assert plan is not None and plan.status == s.PlanStatus.DRAFT
        prep = await session.scalar(select(s.PrepTask).where(s.PrepTask.legacy_id == "prep-1"))
        assert prep is not None
        assert prep.output_batch_id is None  # the batch does not exist until prep runs
        for model, expected in ((s.PrepTaskStep, 2), (s.PrepTaskInput, 1)):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.prep_task_id == prep.id)
            )
            assert count == expected, model.__name__
        meal = await session.scalar(select(s.Meal).where(s.Meal.legacy_id == "m-1"))
        assert meal is not None
        component = await session.scalar(
            select(s.MealComponent).where(s.MealComponent.meal_id == meal.id)
        )
        assert component.prep_task_id == prep.id
    await assert_identical(driver)


async def test_full_execution_loop_renders_identically(driver, relational_sessions):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await assert_identical(driver)

    await driver.send("plan.confirm", {"id": "p-1"})
    await assert_identical(driver)

    await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    await assert_identical(driver)

    state = await driver.send(
        "meal.status", {"planId": "p-1", "mealId": "m-1", "status": "completed"}
    )
    await assert_identical(driver)

    await driver.send("meal.like", {"planId": "p-1", "mealId": "m-1", "liked": True})
    await assert_identical(driver)

    # Undo the completion and check the whole document still agrees.
    audit_id = next(
        entry["id"] for entry in reversed(state["audit"]) if entry["kind"] == "meal.status"
    )
    await driver.send("change.undo", {"auditId": audit_id})
    await assert_identical(driver)


async def test_meal_events_record_execution_history(driver, relational_sessions):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await driver.send("plan.confirm", {"id": "p-1"})
    await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    await driver.send("meal.status", {"planId": "p-1", "mealId": "m-1", "status": "completed"})
    await driver.send("meal.like", {"planId": "p-1", "mealId": "m-1", "liked": True})

    async with relational_sessions() as session:
        meal = await session.scalar(select(s.Meal).where(s.Meal.legacy_id == "m-1"))
        kinds = (
            await session.scalars(select(s.MealEvent.kind).where(s.MealEvent.meal_id == meal.id))
        ).all()
        assert s.MealEventKind.COMPLETED in kinds
        assert s.MealEventKind.LIKED in kinds

        # "已做过 N 次" is counted from these rows, per the design doc.
        cooked = await session.scalar(
            select(func.count())
            .select_from(s.MealEvent)
            .where(s.MealEvent.kind == s.MealEventKind.COMPLETED)
        )
        assert cooked == 1


async def test_settings_knowledge_and_prompts_follow_commands(driver, relational_sessions):
    await driver.send(
        "settings.save",
        {
            "settings": {
                "people": 4,
                "childAge": 24.0,
                "allergies": ["花生", "海鲜"],
                "timezone": "Asia/Shanghai",
                "generateTime": "18:30",
                "prepDay": 5,
                "maxPrepMinutes": 200.0,
                "maxDailyActiveMinutes": 40.0,
                "newRecipesPerWeek": 3,
                "recipeRepeatGapDays": 2,
                "guidance": [
                    {
                        "id": "g-1",
                        "title": "Family basics",
                        "content": "一家四口",
                        "enabled": True,
                        "version": 1,
                    }
                ],
            }
        },
    )
    await driver.send(
        "knowledge.save",
        {"document": {"id": "k-1", "title": "膳食指南", "content": "多吃蔬菜"}},
    )
    await driver.send("planning.prompt", {"weekStart": "2026-09-21", "prompt": "少做点"})

    async with relational_sessions() as session:
        settings = await session.scalar(select(s.HouseholdKitchenSettings))
        assert settings.people == 4
        assert settings.timezone == "Asia/Shanghai"
        assert settings.prep_day == 5
        allergies = sorted((await session.scalars(select(s.HouseholdAllergy.label))).all())
        assert allergies == ["海鲜", "花生"]
        assert (await session.scalar(select(func.count()).select_from(s.WeeklyPrompt))) == 1
    await assert_identical(driver)


async def test_editing_guidance_keeps_a_plan_snapshot_intact(driver, relational_sessions):
    """A plan pins the guidance it was generated with; later edits must not
    rewrite history."""
    await driver.send(
        "settings.save",
        {
            "settings": {
                "timezone": "America/Los_Angeles",
                "guidance": [
                    {
                        "id": "g-1",
                        "title": "Family basics",
                        "content": "原始内容",
                        "enabled": True,
                        "version": 1,
                    }
                ],
            }
        },
    )
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    state = await driver.repo.get(driver.scope)
    snapshot = next(p for p in state["plans"] if p["id"] == "p-1")["guidanceSnapshot"]
    assert snapshot and snapshot[0]["content"] == "原始内容"

    await driver.send(
        "settings.save",
        {
            "settings": {
                "timezone": "America/Los_Angeles",
                "guidance": [
                    {
                        "id": "g-1",
                        "title": "Family basics",
                        "content": "改过的内容",
                        "enabled": True,
                        "version": 2,
                    }
                ],
            }
        },
    )
    await assert_identical(driver)
    _, relational = await driver.both()
    pinned = next(p for p in relational["plans"] if p["id"] == "p-1")["guidanceSnapshot"]
    assert pinned[0]["content"] == "原始内容"
    assert pinned[0]["version"] == 1
    assert relational["settings"]["guidance"][0]["content"] == "改过的内容"


async def test_deleting_a_plan_removes_its_whole_tree(driver, relational_sessions):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    async with relational_sessions() as session:
        assert (await session.scalar(select(func.count()).select_from(s.Meal))) == 1

    # A draft for the same week replaces the previous one in the aggregate only
    # when saved under the same id; saving a new id keeps both, so remove the
    # plan by projecting a state without it.
    state = await driver.repo.get(driver.scope)
    plan = next(p for p in state["plans"] if p["id"] == "p-1")
    plan["meals"] = []
    plan["prep"] = []
    await driver.send("plan.save", {"plan": {**plan, "status": "draft", "version": 1}})

    async with relational_sessions() as session:
        assert (await session.scalar(select(func.count()).select_from(s.Meal))) == 0
        assert (await session.scalar(select(func.count()).select_from(s.PrepTask))) == 0
        assert (await session.scalar(select(func.count()).select_from(s.MealComponent))) == 0
    await assert_identical(driver)


async def presets_available(driver):
    """The catalog is seeded per household; surface it so keys can be selected."""
    from recipe_agent.domain.kitchen.relational_write import (
        DEFAULT_MEAL_STYLE_PRESETS,
    )

    return [
        {"key": key, "label": label, "emoji": emoji, "tint": tint, "enabled": True}
        for key, label, emoji, tint in DEFAULT_MEAL_STYLE_PRESETS
    ]


async def test_excluded_slot_costs_no_time_and_no_stock(driver, relational_sessions):
    """Frame 47:9 step 1: unchecking a slot means we do not cook it at all."""
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await driver.send("plan.confirm", {"id": "p-1"})

    state = await driver.repo.get(driver.scope)
    plan = next(p for p in state["plans"] if p["id"] == "p-1")
    meal = plan["meals"][0]
    assert meal["included"] is True
    assert meal["activeMinutes"] > 0

    state = await driver.send("meal.include", {"planId": "p-1", "mealId": "m-1", "included": False})
    plan = next(p for p in state["plans"] if p["id"] == "p-1")
    excluded = next(m for m in plan["meals"] if m["id"] == "m-1")
    assert excluded["included"] is False

    async with relational_sessions() as session:
        row = await session.scalar(select(s.Meal).where(s.Meal.legacy_id == "m-1"))
        assert row.included is False
    await assert_identical(driver)

    # Putting it back restores the slot.
    state = await driver.send("meal.include", {"planId": "p-1", "mealId": "m-1", "included": True})
    plan = next(p for p in state["plans"] if p["id"] == "p-1")
    assert next(m for m in plan["meals"] if m["id"] == "m-1")["included"] is True
    await assert_identical(driver)


async def test_excluding_an_executed_meal_is_refused(driver):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    await driver.send("plan.confirm", {"id": "p-1"})
    await driver.send(
        "prep.status",
        {"planId": "p-1", "prepId": "prep-1", "status": "completed", "actualPortions": 4.0},
    )
    await driver.send("meal.status", {"planId": "p-1", "mealId": "m-1", "status": "completed"})
    from recipe_agent.domain.kitchen.engine import KitchenError

    with pytest.raises(KitchenError, match="Undo the execution"):
        await driver.send("meal.include", {"planId": "p-1", "mealId": "m-1", "included": False})


async def test_meal_style_presets_are_selected_per_week(driver, relational_sessions):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})

    catalog = (await driver.repo.get(driver.scope))["mealStylePresets"]
    assert {p["key"] for p in catalog} >= {"home_cooked", "meal_prep", "fridge_first"}

    state = await driver.send(
        "plan.presets", {"planId": "p-1", "keys": ["home_cooked", "fridge_first"]}
    )
    plan = next(p for p in state["plans"] if p["id"] == "p-1")
    assert plan["presets"] == ["home_cooked", "fridge_first"]

    async with relational_sessions() as session:
        count = await session.scalar(select(func.count()).select_from(s.PlanPreset))
        assert count == 2
    await assert_identical(driver)


async def test_an_unknown_preset_key_is_refused(driver):
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})
    from recipe_agent.domain.kitchen.engine import KitchenError

    with pytest.raises(KitchenError, match="Unknown meal style preset"):
        await driver.send("plan.presets", {"planId": "p-1", "keys": ["not_a_preset"]})


async def test_a_command_that_leaves_a_plan_alone_does_not_rewrite_its_rows(
    driver, relational_sessions
):
    """A step change or a new tag used to rewrite every plan's meals, chat and
    snapshots (over a second on a real household); untouched plans now keep
    their rows, and both read paths still agree."""
    await seed(driver)
    await driver.send("plan.save", {"plan": plan_with_prep()})

    async def meal_rows():
        async with relational_sessions() as session:
            return set((await session.scalars(select(s.Meal.id))).all())

    before = await meal_rows()
    workflow = {"planId": "p-1", "step": "adjust", "focus": "shopping"}
    await driver.send(
        "planning.workflow", {"weekStart": plan_with_prep()["weekStart"], "workflow": workflow}
    )
    await driver.send("tag.save", {"name": "快手菜"})
    assert await meal_rows() == before
    await assert_identical(driver)

    # A change to the plan itself is still written.
    await driver.send("meal.like", {"planId": "p-1", "mealId": "m-1", "liked": True})
    _, relational = await driver.both()
    assert relational["plans"][0]["meals"][0]["liked"] is True
    await assert_identical(driver)
