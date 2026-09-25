"""Confirmation computes quantities and asks the model only about new recipe work."""

import json
from copy import deepcopy

import pytest

from recipe_agent.domain.kitchen.fulfillment import generate_fulfillment, inputs_hash
from tests.unit.kitchen.test_confirmation import command, setup


class PrepProvider:
    def __init__(self):
        self.requests = []

    async def complete(self, messages, schema):
        self.requests.append(json.loads(messages[1]["content"]))
        # Shopping arithmetic must never depend on optional model fields.
        assert "shopping" not in schema["properties"]
        return {
            "decisions": [
                {
                    "recipeId": r["id"],
                    "prepareAhead": True,
                    "reason": "Batch cook",
                    "steps": r["steps"],
                }
                for r in self.requests[-1]["recipes"]
            ],
            "warnings": [],
        }


async def confirmed():
    state = setup()
    state["plans"][0]["meals"] = state["plans"][0]["meals"][:1]
    provider = PrepProvider()
    p = state["plans"][0]
    output = await generate_fulfillment(provider, state, p)
    return command(
        state, "plan.fulfill", {"id": p["id"], "inputHash": inputs_hash(state, p), "output": output}
    ), provider


def edit(state):
    p = deepcopy(state["plans"][0])
    p.update(id="edit", status="draft", basePlanId=p["id"], baseVersion=p["version"])
    state = command(state, "plan.save", {"plan": p})
    return state, state["plans"][-1]


async def test_empty_prep_becomes_real_batch_and_shopping_is_scaled_once():
    state, provider = await confirmed()
    p = state["plans"][0]
    assert len(provider.requests) == 1
    assert len(p["prep"]) == 1
    assert p["prep"][0]["plannedPortions"] == 3
    assert p["meals"][0]["components"][0]["prepId"] == p["prep"][0]["id"]
    assert p["fulfillment"]["shopping"][0]["required"] == 1
    assert p["fulfillment"]["shopping"][0]["toBuy"] == 1


async def test_unchanged_edit_confirms_without_another_model_call():
    state, provider = await confirmed()
    before = deepcopy(state["plans"][0])
    state, p = edit(state)
    output = await generate_fulfillment(provider, state, p)
    saved = command(
        state, "plan.fulfill", {"id": p["id"], "inputHash": inputs_hash(state, p), "output": output}
    )
    assert len(provider.requests) == 1
    assert saved["plans"][-1]["prep"] == before["prep"]
    assert saved["plans"][-1]["fulfillment"]["shopping"] == before["fulfillment"]["shopping"]


async def test_portion_only_change_recalculates_without_model():
    state, provider = await confirmed()
    state, p = edit(state)
    meal = deepcopy(p["meals"][0])
    meal["components"][0]["portions"] = 6
    state = command(state, "meal.save", {"planId": p["id"], "meal": meal})
    p = state["plans"][-1]
    output = await generate_fulfillment(provider, state, p)
    assert len(provider.requests) == 1
    assert output["prep"][0]["plannedPortions"] == 6
    assert output["shopping"][0]["required"] == 2


async def test_added_recipe_scopes_ai_and_preserves_existing_batch():
    state, provider = await confirmed()
    state, p = edit(state)
    original = deepcopy(p["prep"][0])
    soup = {**deepcopy(state["recipes"][0]), "id": "soup", "name": "汤", "steps": ["Simmer soup"]}
    soup["ingredients"] = [{"name": "胡萝卜", "quantity": 300, "unit": "g"}]
    state["recipes"].append(soup)
    meal = deepcopy(p["meals"][0])
    meal.update(id="new-meal", day="2026-09-23")
    meal["components"] = [
        {"id": "new-food", "name": "汤", "type": "Vegetables", "recipeId": "soup", "portions": 3}
    ]
    p["meals"].append(meal)
    output = await generate_fulfillment(provider, state, p)
    assert [r["id"] for r in provider.requests[-1]["recipes"]] == ["soup"]
    assert all(m["id"] == "new-meal" for m in provider.requests[-1]["plan"]["meals"])
    assert output["prep"][0] == original
    assert len(output["prep"]) == 2
    assert next(i for i in output["shopping"] if i["name"] == "胡萝卜")["toBuy"] == 300


async def test_empty_ai_advice_cannot_silently_drop_all_prep():
    class Empty:
        async def complete(self, messages, schema):
            return {"decisions": [], "warnings": []}

    state = setup()
    with pytest.raises(ValueError, match="every requested recipe"):
        await generate_fulfillment(Empty(), state, state["plans"][0])


async def test_new_prep_deducts_known_raw_stock_only_once_on_completion():
    state = setup()
    state["plans"][0]["meals"] = state["plans"][0]["meals"][:1]
    state["recipes"][0]["ingredients"] = [{"name": "Rice", "quantity": 300, "unit": "g"}]
    state["inventory"] = [
        {
            "id": "raw-rice",
            "name": "Rice",
            "type": "Carbs",
            "portions": 2,
            "portionGrams": 100,
            "location": "fridge",
            "prepared": False,
            "addedOn": "2026-09-21",
            "priority": False,
        }
    ]
    p = state["plans"][0]
    output = await generate_fulfillment(PrepProvider(), state, p)
    assert output["shopping"][0]["toBuy"] == 100
    assert output["prep"][0]["inputs"] == [{"inventoryId": "raw-rice", "portions": 2}]
    saved = command(
        state, "plan.fulfill", {"id": p["id"], "inputHash": inputs_hash(state, p), "output": output}
    )
    assert saved["inventory"][0]["portions"] == 2
    saved = command(
        saved,
        "prep.status",
        {
            "planId": p["id"],
            "prepId": output["prep"][0]["id"],
            "status": "completed",
            "actualPortions": 3,
        },
    )
    assert saved["inventory"][0]["portions"] == 0


def test_shopping_excludes_expired_stock_and_does_not_invent_units():
    from recipe_agent.domain.kitchen.shopping import shopping_list

    state = setup()
    p = state["plans"][0]
    p["meals"] = p["meals"][:1]
    state["recipes"][0]["ingredients"] = [{"name": "Rice", "quantity": 0.3, "unit": "kg"}]
    raw = {"id": "raw", "name": "Rice", "prepared": False, "portions": 10, "type": "Carbs"}
    state["inventory"] = [{**raw, "portionGrams": 100, "expiresOn": "2026-09-20"}]
    items, _ = shopping_list(state, p, "2026-09-21")
    assert (items[0]["required"], items[0]["toBuy"]) == (300, 300)
    state["inventory"] = [raw]
    items, warnings = shopping_list(state, p, "2026-09-21")
    assert items[0]["toBuy"] == 300
    assert len(warnings) == 1


async def test_recipe_edit_updates_only_its_existing_prep_instructions():
    state, provider = await confirmed()
    state, p = edit(state)
    old_id = p["prep"][0]["id"]
    updated = deepcopy(state["recipes"][0])
    updated["steps"] = ["Rinse and cook the revised recipe"]
    state = command(state, "recipe.save", {"recipe": updated})
    p = state["plans"][-1]
    output = await generate_fulfillment(provider, state, p)
    assert output["prep"][0]["id"] == old_id
    assert output["prep"][0]["steps"] == ["Rinse and cook the revised recipe"]
    assert len(provider.requests) == 2
