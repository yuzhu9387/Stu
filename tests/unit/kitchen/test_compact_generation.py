"""The compact AI wire format expands into a fully validated durable weekly draft."""

from itertools import pairwise

import pytest

from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI
from recipe_agent.domain.kitchen.engine import initial_state
from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider, MemoryRepository, recipe


def compact_menu():
    recipes = [
        {
            **recipe(),
            "id": "oats",
            "name": "Banana oatmeal",
            "servings": 12,
            "activeMinutes": 10,
            "elapsedMinutes": 20,
            "equipment": ["pot"],
            "ingredients": [{"name": "Oats", "quantity": 600, "unit": "g"}],
            "steps": ["Cook oats.", "Cool, portion and freeze later servings."],
        },
        {
            **recipe(),
            "id": "eggs",
            "name": "Vegetable egg cups",
            "servings": 9,
            "activeMinutes": 12,
            "elapsedMinutes": 25,
            "equipment": ["oven"],
            "ingredients": [{"name": "Eggs", "quantity": 9, "unit": "whole"}],
            "steps": ["Prepare egg mixture and bake.", "Cool, portion and freeze later servings."],
        },
    ]
    return {
        "recipes": recipes,
        "mealTemplates": [
            {
                "id": identifier,
                "components": [{"source": "prep", "recipeId": identifier, "portions": 3}],
                "activeMinutes": 5,
                "elapsedMinutes": 8,
                "steps": ["Reheat thoroughly, serve and clean up."],
            }
            for identifier in ("oats", "eggs")
        ],
        "days": [
            {"breakfast": identifier, "lunch": identifier, "dinner": identifier}
            for identifier in ("oats", "eggs", "oats", "eggs", "oats", "eggs", "oats")
        ],
    }


async def test_compact_bootstrap_expands_dates_and_aggregates_prep_without_inventing_time():
    repo = MemoryRepository(initial_state())
    provider = FakeProvider(compact_menu())
    result = await KitchenAI(repo, None, provider).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="compact"),
    )
    saved = result["state"]["plans"][0]
    assert len(saved["meals"]) == 21
    assert {m["day"] for m in saved["meals"]} == {f"2026-09-{d}" for d in range(21, 28)}
    assert len({m["id"] for m in saved["meals"]}) == 21
    tasks = {p["recipeId"]: p for p in saved["prep"]}
    assert tasks["oats"]["plannedPortions"] == 36
    assert tasks["oats"]["activeMinutes"] == 30
    assert tasks["oats"]["elapsedMinutes"] == 60
    assert tasks["oats"]["equipment"] == ["pot"]
    assert tasks["eggs"]["plannedPortions"] == 27
    assert tasks["eggs"]["activeMinutes"] == 36
    assert tasks["eggs"]["elapsedMinutes"] == 75
    for meal in saved["meals"]:
        component = meal["components"][0]
        assert component["prepId"] == tasks[component["recipeId"]]["id"]
        assert meal["activeMinutes"] == 5
    assert result["state"]["recipes"][0]["servings"] == 12
    assert result["state"]["recipes"][0]["ingredients"][0]["quantity"] == 600
    assert provider.requests[0][1]["title"] == "CompactGeneration"


async def test_generated_recipes_default_to_no_user_likes():
    output = compact_menu()
    for item in output["recipes"]:
        item.pop("liked")
    repo = MemoryRepository(initial_state())
    provider = FakeProvider(output)
    result = await KitchenAI(repo, None, provider).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="no-likes"),
    )
    assert len(provider.requests) == 1
    assert all(item["liked"] is False for item in result["state"]["recipes"])


async def test_baked_protein_keeps_its_food_type_and_ordinary_prep_time():
    output = compact_menu()
    output["recipes"][0].update(type="Protein", tags=["Baking"])
    repo = MemoryRepository(initial_state())
    result = await KitchenAI(repo, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="baked-protein"),
    )
    task = next(p for p in result["state"]["plans"][0]["prep"] if p["recipeId"] == "oats")
    assert task["type"] == "Protein"


@pytest.mark.parametrize("problem", ["unknown_template", "unknown_recipe"])
async def test_compact_bootstrap_preserves_hard_validators_and_atomicity(problem):
    output = compact_menu()
    if problem == "unknown_template":
        output["days"][0]["breakfast"] = "missing"
    elif problem == "unknown_recipe":
        output["mealTemplates"][0]["components"][0]["recipeId"] = "missing"
    else:
        # One dish for every meal of the week: no order or swap can space it out.
        output["days"] = [{"breakfast": "oats", "lunch": "oats", "dinner": "oats"}] * 7
    repo = MemoryRepository(initial_state())
    errors = {
        "unknown_template": "Unknown meal template",
        "unknown_recipe": "Unknown recipe",
        "consecutive": "repeat",
    }
    with pytest.raises(ValueError, match=errors[problem]):
        await KitchenAI(repo, None, FakeProvider(output)).generate(
            "household",
            GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId=problem),
        )
    assert repo.state["revision"] == 0
    assert repo.state["recipes"] == []
    assert repo.state["plans"] == []


@pytest.mark.parametrize("problem", ["daily_time", "prep_time"])
async def test_a_week_only_over_a_time_limit_is_kept_without_retry(problem):
    """A week a few minutes over a limit beats no week; the analysis flags it."""
    output = compact_menu()
    if problem == "daily_time":
        output["mealTemplates"][0].update(activeMinutes=11, elapsedMinutes=11)
    else:
        output["recipes"][0].update(activeMinutes=100, elapsedMinutes=100)
    repo = MemoryRepository(initial_state())
    provider = FakeProvider(output)
    result = await KitchenAI(repo, None, provider).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId=problem),
    )
    assert len(provider.requests) == 1
    assert len(result["state"]["plans"][0]["meals"]) == 21


async def test_compact_bootstrap_preserves_stock_allocations_and_fresh_cooking_floor():
    state = initial_state()
    state["inventory"] = [
        {
            "id": "rice-stock",
            "name": "Rice",
            "type": "Carbs",
            "portions": 3,
            "location": "Fridge",
            "prepared": True,
            "addedOn": "2026-09-20",
            "priority": True,
        }
    ]
    output = compact_menu()
    output["mealTemplates"].append(
        {
            "id": "stock",
            "components": [{"source": "inventory", "inventoryId": "rice-stock", "portions": 3}],
            "activeMinutes": 2,
            "elapsedMinutes": 3,
            "steps": ["Reheat, serve and clean up"],
        }
    )
    output["days"][0]["lunch"] = "stock"
    output["mealTemplates"][1]["components"][0]["source"] = "fresh"
    output["recipes"][1].update(activeMinutes=4, elapsedMinutes=5)
    repo = MemoryRepository(state)
    result = await KitchenAI(repo, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="stock"),
    )
    saved = result["state"]["plans"][0]
    assert saved["meals"][1]["components"][0]["inventoryId"] == "rice-stock"
    assert all(p["recipeId"] != "eggs" for p in saved["prep"])
    assert "prepId" not in saved["meals"][3]["components"][0]
    assert result["state"]["inventory"][0]["portions"] == 3


async def test_prep_steps_explain_batches_and_real_ingredient_amounts_without_editing_recipe():
    output = compact_menu()
    output["recipes"][0]["steps"][0] = "Use 600 g oats to make 12 portions."
    repo = MemoryRepository(initial_state())
    result = await KitchenAI(repo, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(
            weekStart="2026-09-21", expectedRevision=0, operationId="batch-instructions"
        ),
    )
    saved = result["state"]["plans"][0]
    task = next(p for p in saved["prep"] if p["recipeId"] == "oats")
    text = " ".join(task["steps"])
    assert "3 batches" in text
    assert "12 portions per batch" in text
    assert "36 portions total" in text
    assert "36 planned" in text
    assert "1800 g Oats" in text
    assert "600 g Oats" in text
    assert result["state"]["recipes"][0]["steps"][0] == "Use 600 g oats to make 12 portions."


async def test_compact_prep_inputs_allocate_raw_stock_and_keep_a_draft_that_runs_short():
    state = initial_state()
    state["inventory"] = [
        {
            "id": "raw-oats",
            "name": "Oats (600 g per portion)",
            "type": "Carbs",
            "portions": 3,
            "location": "Pantry",
            "prepared": False,
            "addedOn": "2026-09-20",
            "priority": True,
        }
    ]
    output = compact_menu()
    output["prepInputs"] = [{"recipeId": "oats", "inventoryId": "raw-oats", "portions": 3}]
    repo = MemoryRepository(state)
    result = await KitchenAI(repo, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="raw-input"),
    )
    prep = next(p for p in result["state"]["plans"][0]["prep"] if p["recipeId"] == "oats")
    assert prep["inputs"] == [{"inventoryId": "raw-oats", "portions": 3}]
    assert result["state"]["inventory"][0]["portions"] == 3
    # Asking for more than the pantry holds is a shopping/prep-day need, not a
    # reason to throw the draft away; nothing is consumed until prep is done.
    output["prepInputs"][0]["portions"] = 4
    short = MemoryRepository(state)
    kept = await KitchenAI(short, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="raw-overuse"),
    )
    prep = next(p for p in kept["state"]["plans"][0]["prep"] if p["recipeId"] == "oats")
    assert prep["inputs"] == [{"inventoryId": "raw-oats", "portions": 4}]
    assert kept["state"]["inventory"][0]["portions"] == 3


@pytest.mark.parametrize(
    "allocation",
    [
        {"recipeId": "missing", "inventoryId": "stock", "portions": 1},
        {"recipeId": "oats", "inventoryId": "missing", "portions": 1},
    ],
)
async def test_compact_prep_inputs_cannot_reference_missing_batches_or_stock(allocation):
    output = compact_menu()
    output["prepInputs"] = [allocation]
    repo = MemoryRepository(initial_state())
    with pytest.raises(ValueError, match=r"Unknown (prep recipe|inventory)"):
        await KitchenAI(repo, None, FakeProvider(output)).generate(
            "household",
            GenerateRequest(
                weekStart="2026-09-21", expectedRevision=0, operationId="unknown-input"
            ),
        )
    assert repo.state["revision"] == 0


async def test_fractional_prep_demand_does_not_create_an_extra_batch():
    output = compact_menu()
    output["recipes"][1]["servings"] = 6.3
    output["mealTemplates"][1]["components"][0]["portions"] = 0.7
    repo = MemoryRepository(initial_state())
    result = await KitchenAI(repo, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="fractional"),
    )
    task = next(p for p in result["state"]["plans"][0]["prep"] if p["recipeId"] == "eggs")
    assert task["plannedPortions"] == 6.3
    assert task["activeMinutes"] == 12
    assert task["elapsedMinutes"] == 25


async def test_meals_the_model_put_on_consecutive_days_are_moved_apart():
    from recipe_agent.domain.kitchen.compact_generation import arrange_days

    output = compact_menu()
    # The same menu, but oats and eggs each land on two days in a row.
    output["days"] = [
        {"breakfast": identifier, "lunch": identifier, "dinner": identifier}
        for identifier in ("oats", "oats", "eggs", "eggs", "oats", "eggs", "oats")
    ]
    state = initial_state()
    arranged = arrange_days(state, output, "2026-09-21")
    order = [day["breakfast"] for day in arranged["days"]]
    assert order == ["oats", "eggs", "oats", "eggs", "oats", "eggs", "oats"]
    # Every template keeps its slot and its count.
    assert sorted(order) == sorted(day["breakfast"] for day in output["days"])
    repo = MemoryRepository(state)
    result = await KitchenAI(repo, None, FakeProvider(output)).generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="arranged"),
    )
    assert len(result["state"]["plans"][0]["meals"]) == 21


def test_an_arrangement_that_cannot_work_is_left_for_validation_to_report():
    from recipe_agent.domain.kitchen.compact_generation import arrange_days

    output = compact_menu()
    output["days"] = [{"breakfast": "oats", "lunch": "oats", "dinner": "oats"} for _ in range(7)]
    assert arrange_days(initial_state(), output, "2026-09-21") == output


def test_a_day_over_the_cooking_limit_moves_its_heaviest_fresh_dish_to_prep_day():
    from recipe_agent.domain.kitchen.compact_generation import arrange_days

    output = compact_menu()
    # Egg cups cooked fresh at every meal: 3 x 12 minutes, over a 30-minute day.
    eggs = next(t for t in output["mealTemplates"] if t["id"] == "eggs")
    eggs["components"][0]["source"] = "fresh"
    state = initial_state()
    state["settings"]["maxDailyActiveMinutes"] = 30
    arranged = arrange_days(state, output, "2026-09-21")
    moved = next(t for t in arranged["mealTemplates"] if t["id"] == "eggs")
    assert moved["components"][0]["source"] == "prep"
    # Oats were already prepared ahead and stay untouched.
    assert next(t for t in arranged["mealTemplates"] if t["id"] == "oats") == next(
        t for t in compact_menu()["mealTemplates"] if t["id"] == "oats"
    )


def test_when_counts_cannot_alternate_a_day_borrows_another_meal_of_its_slot():
    from recipe_agent.domain.kitchen.compact_generation import arrange_days

    output = compact_menu()
    output["days"] = [
        {"breakfast": identifier, "lunch": identifier, "dinner": identifier}
        for identifier in ("oats", "oats", "oats", "oats", "oats", "eggs", "eggs")
    ]
    arranged = arrange_days(initial_state(), output, "2026-09-21")
    order = [day["breakfast"] for day in arranged["days"]]
    assert all(a != b for a, b in pairwise(order))
    assert set(order) == {"oats", "eggs"}


def test_a_placeholder_recipe_nothing_uses_is_left_out():
    from recipe_agent.domain.kitchen.compact_generation import drop_unused_recipes

    output = compact_menu()
    placeholder = {**output["recipes"][0], "id": "r", "name": "占位", "incomplete": True}
    output["recipes"].append(placeholder)
    assert [r["id"] for r in drop_unused_recipes(output)["recipes"]] == ["oats", "eggs"]
