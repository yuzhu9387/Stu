"""🔪 + Prep: a dish cooked on prep day from foods already in the fridge. Doing
it takes those foods; only the extra portions, if any, go back in a box, in the
freezer unless the household says the fridge. It can be cooked before the week
it belongs to is confirmed, since it plans nothing for that week."""

import pytest
from pydantic import ValidationError

from recipe_agent.domain.kitchen.contracts import PrepTask
from recipe_agent.domain.kitchen.engine import KitchenError, parse

from .test_dish_baskets import household, portions, run


def fridge_prep(**extra):
    return {
        "id": "egg-pancakes",
        "name": "菠菜鸡蛋饼",
        "type": "Protein",
        "origin": "fridge",
        "plannedPortions": 0,
        "actualPortions": 0,
        "activeMinutes": 10,
        "elapsedMinutes": 15,
        "steps": ["菠菜焯水切碎", "和鸡蛋拌匀", "小火煎熟"],
        "status": "planned",
        "liked": False,
        "inputs": [
            {"inventoryId": "eggs", "portions": 4},
            {"inventoryId": "spinach", "portions": 1},
        ],
        "equipment": [],
        "dependencies": [],
        **extra,
    }


def planned(**extra):
    """The household's draft week, holding one fridge prep."""
    return run(household(), "prep.save", {"planId": "plan", "prep": fridge_prep(**extra)})


def done(state, **payload):
    return run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "egg-pancakes", "status": "completed", **payload},
    )


def box(state):
    return next((i for i in state["inventory"] if i["id"] == "prep-egg-pancakes"), None)


def test_a_fridge_prep_says_where_it_came_from():
    assert parse(PrepTask, fridge_prep())["origin"] == "fridge"
    assert "origin" not in parse(PrepTask, fridge_prep(origin=None))
    with pytest.raises(ValidationError):
        parse(PrepTask, fridge_prep(origin="shop"))


def test_done_takes_the_foods_and_freezes_the_extra():
    state = done(planned(), actualPortions=4)
    assert portions(state)["eggs"] == 6 and portions(state)["spinach"] == 1
    extra = box(state)
    assert (extra["name"], extra["portions"], extra["location"]) == ("菠菜鸡蛋饼", 4, "freezer")
    assert extra["prepared"] is True
    task = state["plans"][0]["prep"][0]
    assert (task["status"], task["actualPortions"]) == ("completed", 4)
    assert task["outputInventoryId"] == "prep-egg-pancakes"


def test_the_extra_can_go_in_the_fridge_instead():
    assert box(done(planned(), actualPortions=2, location="fridge"))["location"] == "fridge"
    with pytest.raises(KitchenError, match="freezer or fridge"):
        done(planned(), actualPortions=2, location="garage")


def test_nothing_extra_leaves_no_box():
    state = done(planned(), actualPortions=0)
    assert box(state) is None
    assert portions(state)["eggs"] == 6
    task = state["plans"][0]["prep"][0]
    assert task["status"] == "completed" and "outputInventoryId" not in task


def test_nothing_extra_leaves_no_box_even_for_a_recipe():
    state = run(
        household(),
        "recipe.save",
        {
            "recipe": {
                "id": "r-pancake",
                "name": "菠菜鸡蛋饼",
                "type": "Protein",
                "mealTypes": ["lunch"],
                "tags": [],
                "servings": 1,
                "activeMinutes": 10,
                "elapsedMinutes": 15,
                "ingredients": [{"name": "鸡蛋", "quantity": 2, "unit": "个"}],
                "steps": ["煎"],
                "liked": False,
                "source": "Manual",
            }
        },
    )
    state = run(state, "prep.save", {"planId": "plan", "prep": fridge_prep(recipeId="r-pancake")})
    assert box(done(state, actualPortions=0)) is None


def test_undo_gives_the_foods_back_and_takes_the_box_away():
    before = planned()
    state = done(before, actualPortions=4)
    undone = run(state, "change.undo", {"auditId": state["audit"][-1]["id"]})
    assert portions(undone) == portions(before)
    task = undone["plans"][0]["prep"][0]
    assert (task["status"], task["actualPortions"]) == ("planned", 0)
    assert "outputInventoryId" not in task


def test_only_fridge_prep_is_cooked_before_the_week_is_confirmed():
    batch = fridge_prep(id="batch", origin=None)
    state = run(planned(), "prep.save", {"planId": "plan", "prep": batch})
    with pytest.raises(KitchenError, match="Only a confirmed plan"):
        run(
            state,
            "prep.status",
            {"planId": "plan", "prepId": "batch", "status": "completed", "actualPortions": 1},
        )


def superseded(state):
    """The week confirmed, then edited as a new version that is confirmed in
    its place: the old version, holding the same + Prep dish, is a draft again."""
    state = run(state, "plan.confirm", {"id": "plan"})
    old = state["plans"][0]
    revision = {
        **old,
        "id": "rev",
        "status": "draft",
        "basePlanId": "plan",
        "baseVersion": old["version"],
    }
    state = run(state, "plan.save", {"plan": revision})
    return run(state, "plan.confirm", {"id": "rev"})


def test_a_superseded_version_cannot_cook_the_dish_again():
    state = superseded(planned())
    assert [p["status"] for p in state["plans"]] == ["draft", "confirmed"]
    with pytest.raises(KitchenError, match="Only a confirmed plan"):
        done(state, actualPortions=1)
    cooked = run(
        state,
        "prep.status",
        {"planId": "rev", "prepId": "egg-pancakes", "status": "completed", "actualPortions": 1},
    )
    assert portions(cooked)["eggs"] == 6


def test_a_superseded_version_cannot_undo_what_it_cooked():
    state = superseded(done(planned(), actualPortions=4))
    cooked = next(a for a in state["audit"] if a["kind"] == "prep.status")
    with pytest.raises(KitchenError, match="superseded"):
        run(state, "change.undo", {"auditId": cooked["id"]})


def test_a_week_holding_only_prep_dishes_is_not_yet_planned():
    from recipe_agent.domain.kitchen.engine import initial_state, prep_only

    week = {"id": "p", "weekStart": "2026-10-05", "status": "draft", "version": 1, "prompt": ""}
    state = run(initial_state(), "inventory.save", {"item": household()["inventory"][0]})
    state = run(
        state,
        "plan.save",
        {"plan": {**week, "meals": [], "prep": [fridge_prep(inputs=[])], "chat": []}},
    )
    plan = state["plans"][0]
    assert prep_only(plan)
    # Opening the week's Plan starts at the first step, not at an empty board.
    assert not any(p.get("workflow") for p in state["weeklyPrompts"])
    assert not prep_only({**plan, "prep": [{**plan["prep"][0], "origin": None}]})
    assert not prep_only({**plan, "status": "confirmed"})
    assert not prep_only({**plan, "prep": []})
    assert not prep_only(planned()["plans"][0])  # a meal planned by hand
