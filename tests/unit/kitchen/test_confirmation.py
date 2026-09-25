from copy import deepcopy

import pytest

from recipe_agent.domain.kitchen.engine import apply_command, initial_state
from recipe_agent.domain.kitchen.fulfillment import inputs_hash
from tests.unit.kitchen.test_ai_scheduling_mcp import plan, recipe


def setup():
    state = initial_state()
    state["recipes"] = [recipe()]
    state["plans"] = [plan()]
    return state


def command(state, kind, payload):
    return apply_command(
        state,
        {
            "type": kind,
            "payload": payload,
            "expectedRevision": state["revision"],
            "operationId": f"op-{state['revision']}",
        },
        "test",
    )["state"]


def test_confirmation_attaches_ai_output_and_rejects_stale_inputs():
    state = setup()
    original = deepcopy(state)
    p = state["plans"][0]
    output = {
        "shopping": [
            {
                "name": "rice",
                "unit": "g",
                "group": "Carbs",
                "required": 300,
                "inStock": 100,
                "toBuy": 200,
                "dishes": ["Rice"],
            }
        ],
        "prep": p["prep"],
        "assignments": [],
        "warnings": [],
    }
    payload = {"id": p["id"], "inputHash": inputs_hash(state, p), "output": output}
    saved = command(state, "plan.fulfill", payload)
    assert saved["plans"][0]["status"] == "confirmed"
    assert saved["plans"][0]["fulfillment"]["shopping"][0]["toBuy"] == 200
    assert saved["weeklyPrompts"][0]["workflow"]["step"] == "shopping"
    original["settings"]["people"] += 1
    with pytest.raises(ValueError, match="changed"):
        command(original, "plan.fulfill", payload)


def test_lock_applies_each_week_and_unlocks_from_any_occurrence():
    state = setup()
    p = state["plans"][0]
    target = p["meals"][0]
    locked = command(
        state, "meal.lock", {"planId": p["id"], "mealId": target["id"], "locked": True}
    )
    assert len(locked["settings"]["recurringMeals"]) == 1
    next_plan = deepcopy(plan())
    next_plan.update(id="next", weekStart="2026-09-28")
    from datetime import date, timedelta

    for meal in next_plan["meals"]:
        meal["day"] = (date.fromisoformat(meal["day"]) + timedelta(days=7)).isoformat()
        meal["id"] = "next-" + meal["id"]
    next_plan["meals"][0]["components"][0]["name"] = "Different dish"
    saved = command(locked, "plan.save", {"plan": next_plan})
    occurrence = saved["plans"][1]["meals"][0]
    assert occurrence["locked"]
    assert occurrence["components"][0]["name"] == target["components"][0]["name"]
    unlocked = command(
        saved, "meal.lock", {"planId": "next", "mealId": occurrence["id"], "locked": False}
    )
    assert not unlocked["settings"]["recurringMeals"]
    assert all(not p["meals"][0]["locked"] for p in unlocked["plans"])


def test_recurring_prep_gets_new_batch_ids_and_never_reuses_old_stock():
    from recipe_agent.domain.kitchen.recurring import apply_recurring

    state = setup()
    meal = state["plans"][0]["meals"][0]
    meal["components"][0].update(prepId="old-prep", inventoryId="old-stock")
    task = {
        "id": "old-prep",
        "name": "Rice",
        "type": "Carbs",
        "recipeId": "rice",
        "plannedPortions": 3,
        "actualPortions": 3,
        "activeMinutes": 2,
        "elapsedMinutes": 10,
        "steps": ["Cook"],
        "status": "completed",
        "liked": False,
        "outputInventoryId": "old-stock",
        "inputs": [],
        "equipment": [],
        "dependencies": [],
    }
    state["settings"]["recurringMeals"] = [
        {"weekday": 0, "slot": "breakfast", "meal": meal, "prep": [task]}
    ]
    following = {"id": "next", "weekStart": "2026-09-28", "meals": [], "prep": []}
    apply_recurring(state, following)
    occurrence = following["meals"][0]
    assert occurrence["locked"] and occurrence["day"] == "2026-09-28"
    assert not occurrence["components"][0].get("inventoryId")
    fresh = following["prep"][0]
    assert occurrence["components"][0]["prepId"] == fresh["id"] != "old-prep"
    assert fresh["status"] == "planned" and fresh["actualPortions"] == 0
    assert not fresh.get("outputInventoryId")


async def test_generator_preserves_the_household_weekly_locked_slot():
    from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider, MemoryRepository

    state = setup()
    p = state["plans"][0]
    p["meals"][0]["components"][0]["name"] = "Pinned breakfast"
    locked = command(
        state, "meal.lock", {"planId": p["id"], "mealId": p["meals"][0]["id"], "locked": True}
    )
    repository = MemoryRepository(locked)
    output = {"plan": plan(), "recipes": []}
    from tests.unit.kitchen.compact_fixtures import compact_fixture

    provider = FakeProvider(compact_fixture(output))
    ai = KitchenAI(repository, None, provider)
    saved = await ai.generate(
        None,
        GenerateRequest(
            weekStart="2026-09-21", expectedRevision=locked["revision"], operationId="lock-gen"
        ),
    )
    generated = next(p for p in saved["state"]["plans"] if p["id"] == saved["planId"])
    assert generated["meals"][0]["locked"]
    assert generated["meals"][0]["components"][0]["name"] == "Pinned breakfast"
    assert "recurringMeals" in provider.requests[0][0][1]["content"]


def test_empty_shopping_cannot_claim_all_known_ingredients_are_covered():
    state = setup()
    p = state["plans"][0]
    with pytest.raises(ValueError, match="omitted known ingredients"):
        command(
            state,
            "plan.fulfill",
            {
                "id": p["id"],
                "inputHash": inputs_hash(state, p),
                "output": {"shopping": [], "prep": [], "assignments": [], "warnings": []},
            },
        )


def test_lock_from_current_edit_draft_can_still_confirm():
    state = setup()
    state = command(state, "plan.confirm", {"id": "plan"})
    draft = deepcopy(state["plans"][0])
    draft.update(id="edit", status="draft", basePlanId="plan", baseVersion=draft["version"])
    state = command(state, "plan.save", {"plan": draft})
    state = command(
        state, "meal.lock", {"planId": "edit", "mealId": draft["meals"][0]["id"], "locked": True}
    )
    saved = command(state, "plan.confirm", {"id": "edit"})
    assert saved["plans"][1]["status"] == "confirmed"


def test_material_edit_invalidates_old_shopping_snapshot():
    state = setup()
    p = state["plans"][0]
    state = command(
        state,
        "plan.fulfill",
        {
            "id": p["id"],
            "inputHash": inputs_hash(state, p),
            "output": {
                "shopping": [],
                "prep": [],
                "assignments": [],
                "warnings": ["Review quantities"],
            },
        },
    )
    changed = deepcopy(state["plans"][0]["meals"][0])
    changed["components"][0]["portions"] += 1
    state = command(state, "meal.save", {"planId": "plan", "meal": changed})
    assert state["plans"][0]["fulfillment"]["stale"]


def test_weekly_replacement_removes_displaced_batch_and_scales_template():
    from recipe_agent.domain.kitchen.recurring import apply_recurring

    state = setup()
    template = deepcopy(state["plans"][0]["meals"][0])
    template["components"][0]["prepId"] = "template-batch"
    task = {
        "id": "template-batch",
        "name": "Rice",
        "type": "Carbs",
        "recipeId": "rice",
        "plannedPortions": 12,
        "actualPortions": 0,
        "activeMinutes": 8,
        "elapsedMinutes": 40,
        "steps": ["Cook"],
        "status": "planned",
        "liked": False,
        "inputs": [],
        "equipment": [],
        "dependencies": [],
    }
    state["settings"]["recurringMeals"] = [
        {"weekday": 0, "slot": "breakfast", "meal": template, "prep": [task]}
    ]
    current = state["plans"][0]
    current["meals"][0]["components"][0]["prepId"] = "displaced-batch"
    current["prep"] = [{**task, "id": "displaced-batch", "plannedPortions": 3}]
    apply_recurring(state, current)
    assert len(current["prep"]) == 1
    assert current["prep"][0]["id"] != "displaced-batch"
    assert current["prep"][0]["plannedPortions"] == template["components"][0]["portions"]


def test_input_hash_ignores_relational_record_and_set_order():
    state = setup()
    p = state["plans"][0]
    state["recipes"][0]["mealTypes"] = ["lunch", "dinner"]
    reordered = deepcopy(state)
    reordered["recipes"][0]["mealTypes"].reverse()
    reordered["plans"][0]["meals"].reverse()
    assert inputs_hash(state, p) == inputs_hash(reordered, reordered["plans"][0])


def test_locking_edit_draft_preserves_shared_week_prep_references():
    from tests.unit.kitchen.test_engine import fixture_state

    state = fixture_state()
    base = state["plans"][0]
    base["meals"][0]["components"][0]["prepId"] = "prep"
    draft = deepcopy(base)
    draft.update(id="edit", status="draft", basePlanId=base["id"], baseVersion=base["version"])
    state = command(state, "plan.save", {"plan": draft})
    state = command(state, "meal.lock", {"planId": "edit", "mealId": "meal", "locked": True})
    assert state["plans"][0]["meals"][0] == state["plans"][1]["meals"][0]
    resaved = command(state, "plan.save", {"plan": state["plans"][1]})
    assert resaved["plans"][1]["baseVersion"] == resaved["plans"][0]["version"]


def test_consuming_shared_stock_invalidates_all_weeks_shopping():
    from tests.unit.kitchen.test_engine import fixture_state

    state = fixture_state()
    other = deepcopy(state["plans"][0])
    other["id"] = "other"
    other["status"] = "draft"
    state["plans"].append(other)
    snapshot = {
        "shopping": [],
        "warnings": ["Review quantities"],
        "generatedAt": "2026-09-24T12:00:00+00:00",
        "source": "ai",
    }
    for p in state["plans"]:
        p["fulfillment"] = deepcopy(snapshot)
    state = command(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "prep", "status": "completed", "actualPortions": 3},
    )
    assert all(p["fulfillment"]["stale"] for p in state["plans"])
