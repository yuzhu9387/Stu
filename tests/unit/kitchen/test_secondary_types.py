"""A dish has one main food group and may contain others: buns are Carbs, with
some Protein and Vegetables."""

from recipe_agent.domain.kitchen.contracts import InventoryItem, Recipe
from recipe_agent.domain.kitchen.engine import parse

from .test_engine import fixture_state, run


def buns(identifier="buns", **extra):
    return {
        "id": identifier,
        "name": "包子",
        "type": "Carbs",
        "portions": 6,
        "location": "Freezer",
        "prepared": True,
        "addedOn": "2026-09-27",
        "priority": False,
        **extra,
    }


def test_the_main_group_is_not_repeated_and_none_means_absent():
    item = parse(InventoryItem, buns(secondaryTypes=["Protein", "Carbs", "Protein", "Vegetables"]))
    assert item["secondaryTypes"] == ["Protein", "Vegetables"]
    assert "secondaryTypes" not in parse(InventoryItem, buns(secondaryTypes=["Carbs"]))
    recipe = {
        "id": "r",
        "name": "包子",
        "type": "Carbs",
        "mealTypes": ["lunch"],
        "tags": [],
        "servings": 1,
        "activeMinutes": 1,
        "elapsedMinutes": 1,
        "ingredients": [],
        "steps": ["蒸热"],
        "liked": False,
        "source": "",
        "secondaryTypes": ["Protein"],
    }
    assert parse(Recipe, recipe)["secondaryTypes"] == ["Protein"]


def test_every_batch_of_a_food_shares_what_else_it_contains():
    state = run(fixture_state(), "inventory.save", {"item": buns(secondaryTypes=["Protein"])})
    # A new batch that says nothing takes the food's.
    state = run(state, "inventory.receive", {"items": [buns("more-buns")]})
    more = next(i for i in state["inventory"] if i["id"] == "more-buns")
    assert more["secondaryTypes"] == ["Protein"]
    # Editing one sets it for all ...
    state = run(state, "inventory.save", {"item": buns(secondaryTypes=["Protein", "Vegetables"])})
    more = next(i for i in state["inventory"] if i["id"] == "more-buns")
    assert more["secondaryTypes"] == ["Protein", "Vegetables"]
    # ... and clearing it on an existing batch clears it everywhere.
    state = run(state, "inventory.save", {"item": buns()})
    assert all("secondaryTypes" not in i for i in state["inventory"] if i["name"] == "包子")


def test_a_dish_on_a_plate_names_its_own_other_groups():
    from recipe_agent.domain.kitchen.contracts import MealComponent

    dish = {"id": "c", "name": "包子", "type": "Carbs", "portions": 1}
    assert "secondaryTypes" not in parse(MealComponent, dish)
    own = parse(MealComponent, {**dish, "secondaryTypes": ["Protein", "Carbs", "Protein"]})
    assert own["secondaryTypes"] == ["Protein"]
    # An empty list is kept: "none", whatever the recipe says.
    assert parse(MealComponent, {**dish, "secondaryTypes": []})["secondaryTypes"] == []
