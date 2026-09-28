"""A dish cooked from a basket of fridge foods: Stu composes it, and eating the
meal takes what it used from each food."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from recipe_agent.domain.kitchen.ai import ComposeRequest, KitchenAI
from recipe_agent.domain.kitchen.contracts import MealComponent
from recipe_agent.domain.kitchen.engine import (
    KitchenError,
    initial_state,
    inventory_references,
    parse,
)
from recipe_agent.domain.kitchen.shopping import shopping_list
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository
from tests.unit.kitchen.test_ai_variety import SequenceProvider

from .test_engine import run

WEEK = "2026-09-14"


def food(identifier, name, portions, kind="Vegetables"):
    return {
        "id": identifier,
        "name": name,
        "type": kind,
        "portions": portions,
        "location": "fridge",
        "prepared": False,
        "addedOn": "2026-09-13",
        "priority": False,
    }


def pancake(**extra):
    return {
        "id": "pancake",
        "name": "菠菜鸡蛋饼",
        "type": "Protein",
        "portions": 1,
        "uses": [{"inventoryId": "eggs", "portions": 2}, {"inventoryId": "spinach", "portions": 1}],
        **extra,
    }


def recipe(**extra):
    return {
        "id": "r-pancake",
        "name": "菠菜鸡蛋饼",
        "type": "Protein",
        "mealTypes": ["lunch"],
        "tags": [],
        "servings": 1,
        "activeMinutes": 10,
        "elapsedMinutes": 15,
        "ingredients": [
            {"name": "鸡蛋", "quantity": 2, "unit": "个"},
            {"name": "菠菜", "quantity": 50, "unit": "g"},
            {"name": "面粉", "quantity": 30, "unit": "g"},
        ],
        "steps": ["菠菜焯水切碎", "和鸡蛋面粉拌匀", "小火煎熟"],
        "liked": False,
        "source": "Composed from fridge",
        **extra,
    }


def household(component=None, day=WEEK, recipes=()):
    state = initial_state()
    for saved in recipes:
        state = run(state, "recipe.save", {"recipe": saved})
    for item in (food("eggs", "鸡蛋", 10, "Protein"), food("spinach", "菠菜", 2)):
        state = run(state, "inventory.save", {"item": item})
    meal = {
        "id": "lunch",
        "day": day,
        "slot": "lunch",
        "components": [component or pancake()],
        "activeMinutes": 10,
        "elapsedMinutes": 15,
        "steps": ["菠菜鸡蛋饼: 小火煎熟"],
        "status": "planned",
        "liked": False,
        "locked": False,
    }
    monday = datetime.fromisoformat(day).date()
    monday -= timedelta(days=monday.weekday())
    plan = {
        "id": "plan",
        "weekStart": monday.isoformat(),
        "status": "draft",
        "version": 1,
        "prompt": "",
        "meals": [meal],
        "prep": [],
        "chat": [],
    }
    return run(state, "plan.save", {"plan": plan})


def portions(state):
    return {item["id"]: item["portions"] for item in state["inventory"]}


def test_a_dish_names_its_fridge_foods_or_one_batch_never_both():
    with pytest.raises(ValidationError, match="cannot also come from one batch"):
        parse(MealComponent, pancake(inventoryId="eggs"))
    assert "uses" not in parse(MealComponent, pancake(uses=[]))


def test_eating_the_meal_takes_each_food_and_undo_gives_it_back():
    state = run(household(), "plan.confirm", {"id": "plan"})
    eaten = run(state, "meal.status", {"planId": "plan", "mealId": "lunch", "status": "completed"})
    assert portions(eaten) == {"eggs": 8, "spinach": 1}
    undone = run(eaten, "change.undo", {"auditId": eaten["audit"][-1]["id"]})
    assert portions(undone) == {"eggs": 10, "spinach": 2}


def test_a_shortage_names_the_food_that_ran_out():
    uses = [{"inventoryId": "eggs", "portions": 2}, {"inventoryId": "spinach", "portions": 3}]
    state = run(household(pancake(uses=uses)), "plan.confirm", {"id": "plan"})
    with pytest.raises(KitchenError, match="Insufficient stock for 菠菜"):
        run(state, "meal.status", {"planId": "plan", "mealId": "lunch", "status": "completed"})


def test_an_unknown_fridge_food_is_refused():
    uses = [{"inventoryId": "gone", "portions": 1}]
    with pytest.raises(KitchenError, match="unknown fridge food"):
        household(pancake(uses=uses))


def test_a_food_a_coming_meal_uses_stays_and_a_past_meal_lets_it_go():
    today = datetime.now(ZoneInfo("UTC")).date()
    coming = household(day=today.isoformat())
    coming["settings"]["timezone"] = "UTC"
    assert {"eggs", "spinach"} <= inventory_references(coming)
    with pytest.raises(KitchenError, match="Replace it in that meal first"):
        run(coming, "inventory.delete", {"id": "spinach"})
    past = run(household(), "inventory.delete", {"id": "spinach"})
    component = past["plans"][0]["meals"][0]["components"][0]
    assert component["uses"] == [{"inventoryId": "eggs", "portions": 2}]
    gone = run(past, "inventory.delete", {"id": "eggs"})
    assert "uses" not in gone["plans"][0]["meals"][0]["components"][0]


def test_shopping_buys_only_what_the_fridge_does_not_have():
    state = household(pancake(recipeId="r-pancake"), recipes=[recipe()])
    rows, warnings = shopping_list(state, state["plans"][0], as_of=WEEK)
    assert [row["name"] for row in rows if row["toBuy"] > 0] == ["面粉"]
    assert warnings == []
    bare = household()
    rows, warnings = shopping_list(bare, bare["plans"][0], as_of=WEEK)
    assert rows == [] and warnings == []


def test_a_composed_dish_needs_no_recipe_to_count_its_time():
    from recipe_agent.domain.kitchen.scheduling import plan_rule_violations

    state = household()
    assert [
        v for v in plan_rule_violations(state, state["plans"][0]) if v["kind"] == "recipe"
    ] == []


async def test_stu_composes_one_dish_from_the_basket():
    state = household()
    state["settings"]["people"] = 1
    state["settings"]["guidance"] = [
        {"id": "kid", "title": "以娃为主", "content": "忌辛辣", "enabled": True, "version": 1},
        {"id": "off", "title": "Old", "content": "unused", "enabled": False, "version": 1},
    ]
    answer = {
        "recipe": recipe(id="model-id", source="whatever", secondaryTypes=["Vegetables", "Carbs"])
        | {
            "ingredients": [
                {"name": "鸡蛋", "quantity": 2, "unit": "个"},
                {"name": "菠菜", "quantity": 50, "unit": "g"},
                {"name": "盐", "quantity": 0, "unit": "适量"},
            ]
        },
        "uses": [
            {"inventoryId": "eggs", "portions": 2},
            {"inventoryId": "spinach", "portions": 5},
            {"inventoryId": "not-chosen", "portions": 1},
        ],
    }
    provider = SequenceProvider(answer)
    ai = KitchenAI(MemoryRepository(deepcopy(state)), None, provider)
    result = await ai.compose(
        "household",
        ComposeRequest(
            inventoryIds=["eggs", "spinach", "missing"], slot="lunch", mealDishes=["米饭"]
        ),
    )
    composed = result["recipe"]
    assert composed["id"] != "model-id" and composed["source"] == "Composed from fridge"
    assert composed["secondaryTypes"] == ["Vegetables", "Carbs"]
    assert [i["name"] for i in composed["ingredients"]] == ["鸡蛋", "菠菜"]
    # Never more than the fridge has, and only foods from the basket.
    assert result["uses"] == [
        {"inventoryId": "eggs", "portions": 2},
        {"inventoryId": "spinach", "portions": 2},
    ]
    sent = json.loads(provider.requests[0][1]["content"])
    assert [item["id"] for item in sent["basket"]] == ["eggs", "spinach"]
    assert sent["mealDishes"] == ["米饭"] and sent["settings"]["people"] == 1
    assert [g["title"] for g in sent["settings"]["guidance"]] == ["以娃为主"]


async def test_an_empty_basket_is_refused_before_asking_stu():
    provider = SequenceProvider()
    ai = KitchenAI(MemoryRepository(household()), None, provider)
    with pytest.raises(ValueError, match="in the fridge"):
        await ai.compose("household", ComposeRequest(inventoryIds=["missing"]))
    assert provider.requests == []
