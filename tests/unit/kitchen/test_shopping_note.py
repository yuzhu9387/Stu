"""The shopping note on the fridge door: a plain list to add to, tick and put
away. Putting rows away brings them into the fridge the way received shopping
comes in, sharing what the fridge already knows about a food, and takes them
off the list."""

import pytest
from pydantic import ValidationError

from recipe_agent.api.v1.kitchen_mcp import COMMANDS
from recipe_agent.domain.kitchen.contracts import ShoppingItem
from recipe_agent.domain.kitchen.engine import KitchenError, initial_state, parse

from .test_engine import run


def milk(**extra):
    return {"id": "milk", "name": "牛奶", "quantity": 2, "checked": False, **extra}


def listed(*rows):
    state = initial_state()
    for row in rows:
        state = run(state, "shopping.save", {"item": row})
    return state


def stocked(name="牛奶", **extra):
    item = {
        "id": "old",
        "name": name,
        "type": "Dairy",
        "portions": 1,
        "location": "fridge",
        "prepared": False,
        "addedOn": "2026-09-20",
        "priority": False,
        "emoji": "🥛",
        **extra,
    }
    return run(initial_state(), "inventory.save", {"item": item})


def test_a_new_workspace_has_an_empty_note():
    assert initial_state()["shoppingList"] == []


def test_rows_are_added_ticked_changed_and_deleted_in_place():
    state = listed(milk(), {"id": "eggs", "name": " 鸡蛋 ", "checked": False})
    assert [row["name"] for row in state["shoppingList"]] == ["牛奶", "鸡蛋"]
    assert "quantity" not in state["shoppingList"][1]
    state = run(state, "shopping.save", {"item": milk(checked=True, quantity=3)})
    assert state["shoppingList"][0] == milk(checked=True, quantity=3)
    state = run(state, "shopping.delete", {"id": "eggs"})
    assert [row["id"] for row in state["shoppingList"]] == ["milk"]
    with pytest.raises(KitchenError):
        run(state, "shopping.delete", {"id": "eggs"})


def test_a_row_needs_a_name_and_a_sensible_amount():
    with pytest.raises(KitchenError, match="name"):
        listed(milk(name="   "))
    with pytest.raises(ValidationError):
        parse(ShoppingItem, milk(quantity=-1))
    with pytest.raises(ValidationError):
        parse(ShoppingItem, milk(unit="L"))


def test_putting_away_brings_rows_into_the_fridge_and_off_the_list():
    state = listed(milk(checked=True), {"id": "bread", "name": "面包", "checked": True})
    state = run(
        state,
        "shopping.putAway",
        {"items": [{"id": "milk"}, {"id": "bread", "location": "Freezer", "portions": 3}]},
    )
    assert state["shoppingList"] == []
    milk_box, bread = state["inventory"]
    # A number on the row is how many portions; otherwise one, in the fridge.
    assert (milk_box["name"], milk_box["portions"], milk_box["location"]) == ("牛奶", 2, "fridge")
    assert (milk_box["type"], milk_box["prepared"], milk_box["priority"]) == ("Other", False, False)
    assert (bread["portions"], bread["location"]) == (3, "freezer")
    assert milk_box["id"] not in {"milk", "bread"} and milk_box["id"] != bread["id"]


def test_only_the_rows_put_away_leave_the_note():
    state = listed(milk(checked=True), {"id": "bread", "name": "面包", "checked": False})
    state = run(state, "shopping.putAway", {"items": [{"id": "milk"}]})
    assert [row["id"] for row in state["shoppingList"]] == ["bread"]


def test_a_food_already_in_the_fridge_keeps_its_type_and_icon():
    state = run(stocked(), "shopping.save", {"item": milk(checked=True)})
    state = run(
        state,
        "shopping.putAway",
        {"items": [{"id": "milk", "location": "freezer", "type": "Other"}]},
    )
    new = next(i for i in state["inventory"] if i["id"] != "old")
    assert (new["type"], new["emoji"], new["location"]) == ("Dairy", "🥛", "freezer")
    assert {i["type"] for i in state["inventory"]} == {"Dairy"}


def test_a_new_food_takes_the_type_it_is_given():
    state = run(listed(milk()), "shopping.putAway", {"items": [{"id": "milk", "type": "Dairy"}]})
    assert state["inventory"][0]["type"] == "Dairy"


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"id": "nope"}],
        [{"id": "milk"}, {"id": "milk"}],
        [{"id": "milk", "portions": 0}],
        [{"id": "milk", "location": "  "}],
        [{"id": "milk", "type": "Snacks"}],
    ],
)
def test_putting_away_refuses_what_it_cannot_do(items):
    with pytest.raises(KitchenError):
        run(listed(milk()), "shopping.putAway", {"items": items})


def test_the_note_is_offered_to_the_assistant():
    assert {"shopping.save", "shopping.delete", "shopping.putAway"} <= set(COMMANDS)
