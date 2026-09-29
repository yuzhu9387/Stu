"""A dish keeps its own ingredients and time when it has no recipe, and a
meal that went differently is recorded as Changed, with a note."""

import pytest
from pydantic import ValidationError

from recipe_agent.domain.kitchen.contracts import Meal, MealComponent
from recipe_agent.domain.kitchen.engine import KitchenError, parse
from recipe_agent.domain.kitchen.scheduling import plan_rule_violations, recompute_plan_timing
from recipe_agent.domain.kitchen.shopping import shopping_list

from .test_dish_baskets import WEEK, household, pancake, portions, run

SPINACH = {
    "id": "greens",
    "name": "蒜蓉菠菜",
    "type": "Vegetables",
    "portions": 2,
    "ingredients": [
        {"name": "菠菜", "quantity": 200, "unit": "g"},
        {"name": "蒜", "quantity": 2, "unit": "瓣"},
        {"name": "盐", "quantity": 1, "unit": "g"},
    ],
    "activeMinutes": 8,
    "elapsedMinutes": 10,
}


def test_a_dish_names_its_own_ingredients_and_time():
    dish = parse(MealComponent, SPINACH)
    assert dish["ingredients"][0] == {"name": "菠菜", "quantity": 200, "unit": "g"}
    assert (dish["activeMinutes"], dish["elapsedMinutes"]) == (8, 10)
    assert "ingredients" not in parse(MealComponent, {**SPINACH, "ingredients": None})


def test_a_recipe_less_dish_is_shopped_and_timed_from_its_own_details():
    state = household(SPINACH)
    plan = state["plans"][0]
    rows, _ = shopping_list(state, plan, as_of=WEEK)
    # Its own amounts for the portions eaten; salt is never bought; the
    # fridge's spinach is not this dish's (it takes nothing from it).
    garlic = next(row for row in rows if row["name"] == "蒜")
    assert garlic["required"] == 2
    assert "盐" not in {row["name"] for row in rows}
    timed = recompute_plan_timing(state, plan)["meals"][0]
    assert timed["activeMinutes"] >= 8
    assert not [v for v in plan_rule_violations(state, plan) if v["kind"] == "recipe"]


def test_a_changed_meal_keeps_the_fridge_and_its_note_and_can_be_undone():
    state = run(household(), "plan.confirm", {"id": "plan"})
    changed = run(
        state,
        "meal.status",
        {"planId": "plan", "mealId": "lunch", "status": "changed", "note": "改成了包子"},
    )
    meal = changed["plans"][0]["meals"][0]
    assert (meal["status"], meal["note"]) == ("changed", "改成了包子")
    assert portions(changed) == portions(state)
    undone = run(changed, "change.undo", {"auditId": changed["audit"][-1]["id"]})
    back = undone["plans"][0]["meals"][0]
    assert back["status"] == "planned" and "note" not in back


def test_changed_needs_no_note_but_a_long_one_is_refused():
    state = run(household(pancake()), "plan.confirm", {"id": "plan"})
    quiet = run(state, "meal.status", {"planId": "plan", "mealId": "lunch", "status": "changed"})
    assert "note" not in quiet["plans"][0]["meals"][0]
    with pytest.raises(KitchenError):
        run(
            state,
            "meal.status",
            {"planId": "plan", "mealId": "lunch", "status": "changed", "note": "x" * 501},
        )
    with pytest.raises(ValidationError):
        parse(Meal, {**state["plans"][0]["meals"][0], "note": "x" * 501})
