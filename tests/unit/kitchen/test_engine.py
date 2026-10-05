from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from recipe_agent.domain.kitchen.engine import KitchenError, apply_command, find, initial_state


def run(state, kind, payload):
    return apply_command(
        state,
        {
            "type": kind,
            "payload": payload,
            "expectedRevision": state["revision"],
            "operationId": str(state["revision"]),
        },
        "actor",
    )["state"]


def fixture_state():
    state = initial_state()
    for identifier, portions in [("protein", 2), ("carbs", 6), ("veg", 4)]:
        state = run(
            state,
            "inventory.save",
            {
                "item": {
                    "id": identifier,
                    "name": identifier,
                    "type": "Other",
                    "portions": portions,
                    "location": "fridge",
                    "prepared": True,
                    "addedOn": "2026-09-14",
                    "priority": False,
                }
            },
        )
    prep = {
        "id": "prep",
        "name": "protein",
        "type": "Other",
        "plannedPortions": 3,
        "actualPortions": 0,
        "activeMinutes": 5,
        "elapsedMinutes": 10,
        "steps": ["Cook"],
        "status": "planned",
        "liked": False,
        "outputInventoryId": "protein",
        "inputs": [],
        "equipment": [],
        "dependencies": [],
    }
    meal = {
        "id": "meal",
        "day": "2026-09-14",
        "slot": "dinner",
        "components": [
            {"id": x, "name": x, "type": "Other", "portions": 3, "inventoryId": x}
            for x in ["protein", "carbs", "veg"]
        ],
        "activeMinutes": 10,
        "elapsedMinutes": 15,
        "steps": ["Serve"],
        "status": "planned",
        "liked": False,
        "locked": False,
    }
    plan = {
        "id": "plan",
        "weekStart": "2026-09-14",
        "status": "draft",
        "version": 1,
        "prompt": "",
        "meals": [meal],
        "prep": [prep],
        "chat": [],
    }
    state = run(state, "plan.save", {"plan": plan})
    return run(state, "plan.confirm", {"id": "plan"})


def balances(state):
    return [x["portions"] for x in state["inventory"]]


def test_stock_ledger_and_undo_preserves_like():
    state = fixture_state()
    assert balances(state) == [2, 6, 4]
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    assert balances(state) == [5, 6, 4]
    state = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    audit = state["audit"][-1]["id"]
    assert balances(state) == [2, 3, 1]
    state = run(state, "meal.like", {"planId": "plan", "mealId": "meal", "liked": True})
    state = run(state, "change.undo", {"auditId": audit})
    assert balances(state) == [5, 6, 4]
    assert state["plans"][0]["meals"][0]["liked"] is True


def test_insufficient_stock_atomic_and_completed_cannot_repeat():
    state = fixture_state()
    before = deepcopy(state)
    with pytest.raises(KitchenError, match="Insufficient"):
        run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    assert state == before
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    after = run(state, "prep.status", {"planId": "plan", "prepId": "prep", "status": "completed"})
    assert balances(after) == balances(state)


def test_negative_and_stale_rejected():
    state = fixture_state()
    item = {**state["inventory"][0], "portions": -1}
    with pytest.raises(ValueError):
        run(state, "inventory.save", {"item": item})
    with pytest.raises(KitchenError):
        apply_command(
            state,
            {
                "type": "tag.save",
                "payload": {"name": "x"},
                "expectedRevision": 0,
                "operationId": "stale",
            },
            "actor",
        )


def test_consumed_prep_cannot_be_undone():
    state = fixture_state()
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    audit = state["audit"][-1]["id"]
    state = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    with pytest.raises(KitchenError):
        run(state, "change.undo", {"auditId": audit})


def test_partial_prep_skip_and_dirty_versions():
    state = fixture_state()
    old_version = state["plans"][0]["version"]
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 0.5},
    )
    assert balances(state) == [2.5, 6, 4]
    assert state["plans"][0]["version"] == old_version + 1
    with pytest.raises(KitchenError, match="Insufficient"):
        run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    state = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "skipped"})
    assert balances(state) == [2.5, 6, 4]
    with pytest.raises(KitchenError, match="Undo"):
        run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})


def test_confirmed_plan_cannot_be_overwritten_and_base_conflict():
    state = fixture_state()
    draft = deepcopy(state["plans"][0])
    with pytest.raises(KitchenError):
        run(state, "plan.save", {"plan": draft})
    draft.update(id="draft", status="draft", basePlanId="plan", baseVersion=draft["version"])
    state = run(state, "plan.save", {"plan": draft})
    state = run(state, "meal.lock", {"planId": "plan", "mealId": "meal", "locked": True})
    with pytest.raises(KitchenError, match="changed"):
        run(state, "plan.confirm", {"id": "draft"})


def this_week(state):
    """The fixture's week moved to now, its meal still to eat today."""
    current = deepcopy(state)
    today = datetime.now(ZoneInfo(current["settings"]["timezone"])).date()
    current["plans"][0]["weekStart"] = (today - timedelta(days=today.weekday())).isoformat()
    for meal in current["plans"][0]["meals"]:
        meal["day"] = today.isoformat()
    return current


def take_out(state, identifier):
    return apply_command(
        state,
        {
            "type": "inventory.delete",
            "payload": {"id": identifier},
            "expectedRevision": state["revision"],
            "operationId": f"out-{identifier}",
        },
        "actor",
    )


def test_a_food_a_coming_meal_uses_is_still_taken_out_and_the_meal_lets_go():
    current = this_week(fixture_state())
    weekday = current["plans"][0]["meals"][0]["day"]
    result = take_out(current, "protein")
    removed = result["state"]
    assert "protein" not in {i["id"] for i in removed["inventory"]}
    meal = removed["plans"][0]["meals"][0]
    assert [c.get("inventoryId") for c in meal["components"]] == [None, "carbs", "veg"]
    # The meal keeps its dish; the message says which meal no longer uses the food.
    assert meal["components"][0]["name"] == "protein"
    day = datetime.fromisoformat(weekday).strftime("%a")
    assert result["message"] == f"Removed from the fridge; {day} dinner no longer uses it"
    # A meal from a week gone by only remembers where its food came from.
    past = run(fixture_state(), "inventory.delete", {"id": "protein"})
    assert all(
        c.get("inventoryId") != "protein"
        for m in past["plans"][0]["meals"]
        for c in m["components"]
    )


def test_a_meal_left_out_is_not_named_when_its_food_is_taken_out():
    current = this_week(fixture_state())
    current["plans"][0]["meals"][0]["included"] = False
    assert take_out(current, "carbs")["message"] == "Removed from the fridge"


def test_a_food_prep_still_to_cook_needs_is_still_taken_out():
    state = fixture_state()
    state["plans"][0]["prep"][0]["inputs"] = [{"inventoryId": "veg", "portions": 1}]
    current = this_week(state)
    result = take_out(current, "veg")
    task = result["state"]["plans"][0]["prep"][0]
    assert task["inputs"] == []
    assert "protein prep" in result["message"]
    # The prep still cooks, from what is left.
    done = run(
        result["state"],
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    assert find(done["plans"][0]["prep"], "prep")["status"] == "completed"


def test_a_meal_whose_prepped_box_was_taken_out_can_still_be_eaten():
    state = fixture_state()
    state["plans"][0]["meals"][0]["components"][0] = {
        "id": "protein",
        "name": "protein",
        "type": "Other",
        "portions": 3,
        "prepId": "prep",
    }
    state = this_week(state)
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    state = run(state, "inventory.delete", {"id": "protein"})
    eaten = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    assert eaten["plans"][0]["meals"][0]["status"] == "completed"
    # The rest of the meal still comes out of the fridge.
    assert balances(eaten) == [3, 1]


def test_execution_cannot_be_forged_through_a_draft():
    state = fixture_state()
    draft = deepcopy(state["plans"][0])
    draft.update(id="draft", status="draft", basePlanId="plan", baseVersion=draft["version"])
    draft["meals"][0]["status"] = "completed"
    with pytest.raises(KitchenError, match="Execution"):
        run(state, "plan.save", {"plan": draft})


def test_meal_edit_preserves_time_when_over_daily_target():
    state = fixture_state()
    meal = deepcopy(state["plans"][0]["meals"][0])
    meal.update(activeMinutes=31, elapsedMinutes=35)
    saved = run(state, "meal.save", {"planId": "plan", "meal": meal})
    assert saved["plans"][0]["meals"][0]["activeMinutes"] == 31


def test_execution_undo_rejected_after_plan_superseded():
    state = fixture_state()
    state = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "skipped"})
    audit = state["audit"][-1]["id"]
    draft = deepcopy(state["plans"][0])
    draft.update(id="replacement", status="draft", basePlanId="plan", baseVersion=draft["version"])
    state = run(state, "plan.save", {"plan": draft})
    state = run(state, "plan.confirm", {"id": "replacement"})
    with pytest.raises(KitchenError, match="superseded"):
        run(state, "change.undo", {"auditId": audit})


def test_prep_dependency_cycle_is_invalid_even_in_draft():
    state = fixture_state()
    draft = deepcopy(state["plans"][0])
    draft.update(id="draft", status="draft", basePlanId="plan", baseVersion=draft["version"])
    draft["prep"].append({**deepcopy(draft["prep"][0]), "id": "second", "dependencies": ["prep"]})
    draft["prep"][0]["dependencies"] = ["second"]
    with pytest.raises(KitchenError, match="cyclic"):
        run(state, "plan.save", {"plan": draft})


def test_confirm_accounts_for_other_weeks_planned_prep_supply():
    state = fixture_state()
    # Existing first week's confirmed meal consumes its own planned prep output.
    draft = deepcopy(state["plans"][0])
    draft.update(id="next-week", weekStart="2026-09-21", status="draft")
    draft["meals"][0]["day"] = "2026-09-21"
    draft["meals"][0]["components"] = [draft["meals"][0]["components"][0]]
    draft["meals"][0]["components"][0]["portions"] = 1
    draft["prep"] = []
    state = run(state, "plan.save", {"plan": draft})
    state = run(state, "plan.confirm", {"id": "next-week"})
    assert balances(state) == [2, 6, 4]


def test_prep_reference_cannot_use_a_different_inventory_batch():
    state = fixture_state()
    meal = deepcopy(state["plans"][0]["meals"][0])
    meal["components"][0].update(prepId="prep", inventoryId="carbs")
    with pytest.raises(KitchenError, match="different"):
        run(state, "meal.save", {"planId": "plan", "meal": meal})


def test_undo_does_not_restore_consumption_into_repurposed_inventory():
    state = fixture_state()
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    state = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    audit = state["audit"][-1]["id"]
    state = run(state, "inventory.save", {"item": {**state["inventory"][1], "name": "other food"}})
    with pytest.raises(KitchenError, match="Stock changed"):
        run(state, "change.undo", {"auditId": audit})


def test_fresh_recipe_confirm_and_complete_do_not_consume_matching_fridge_stock():
    state = fixture_state()
    recipe = {
        "id": "fresh",
        "name": "Fresh rice",
        "type": "Carbs",
        "mealTypes": ["dinner"],
        "tags": [],
        "servings": 3,
        "activeMinutes": 5,
        "elapsedMinutes": 10,
        "ingredients": [{"name": "Rice", "quantity": 100, "unit": "g"}],
        "steps": ["Cook rice"],
        "liked": False,
        "source": "manual",
    }
    state = run(state, "recipe.save", {"recipe": recipe})
    draft = deepcopy(state["plans"][0])
    draft.update(id="fresh-plan", weekStart="2026-09-21", status="draft")
    draft["prep"] = []
    draft["meals"][0]["day"] = "2026-09-21"
    draft["meals"][0]["components"] = [
        {"id": "fresh-c", "name": "Fresh rice", "type": "Carbs", "recipeId": "fresh", "portions": 3}
    ]
    state = run(state, "plan.save", {"plan": draft})
    # Recipe-only cooking must also work with no matching on-hand portions.
    state = run(state, "plan.confirm", {"id": "fresh-plan"})
    state = run(
        state,
        "inventory.save",
        {
            "item": {
                "id": "leftovers",
                "name": "Fresh rice",
                "type": "Carbs",
                "recipeId": "fresh",
                "portions": 2,
                "prepared": True,
                "location": "Fridge",
                "addedOn": "2026-09-17",
                "priority": False,
            }
        },
    )
    before = deepcopy(state["inventory"])
    state = run(
        state, "meal.status", {"planId": "fresh-plan", "mealId": "meal", "status": "completed"}
    )
    assert state["inventory"] == before
    assert state["audit"][-1]["deltas"] == []


def test_a_stock_shortage_does_not_block_confirming():
    # What the week needs beyond the fridge is prepared on prep day.
    state = fixture_state()
    draft = deepcopy(state["plans"][0])
    draft.update(id="short-week", weekStart="2026-09-21", status="draft", prep=[])
    draft["meals"][0]["day"] = "2026-09-21"
    draft["meals"][0]["components"] = [draft["meals"][0]["components"][0]]
    draft["meals"][0]["components"][0]["portions"] = 999
    state = run(state, "plan.save", {"plan": draft})
    state = run(state, "plan.confirm", {"id": "short-week"})
    assert next(p for p in state["plans"] if p["id"] == "short-week")["status"] == "confirmed"
    # Confirming reserves nothing: stock only moves when meals are cooked.
    assert balances(state) == balances(fixture_state())


def test_a_meal_waiting_on_skipped_prep_still_blocks_confirming():
    state = fixture_state()
    draft = deepcopy(state["plans"][0])
    draft.update(id="skip-week", weekStart="2026-09-21", status="draft")
    draft["meals"][0]["day"] = "2026-09-21"
    draft["prep"][0]["status"] = "skipped"
    draft["meals"][0]["components"][0]["prepId"] = draft["prep"][0]["id"]
    state["plans"].append(draft)
    with pytest.raises(KitchenError, match="skipped prep"):
        run(state, "plan.confirm", {"id": "skip-week"})
