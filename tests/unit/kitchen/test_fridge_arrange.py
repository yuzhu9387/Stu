"""Boxes are dragged around the fridge; batch-cooked food lands in the freezer."""

from copy import deepcopy

import pytest

from recipe_agent.domain.kitchen.engine import KitchenError

from .test_engine import fixture_state, run


def test_dragging_boxes_reorders_them_and_moves_one_to_the_freezer():
    state = fixture_state()
    before = deepcopy(state["inventory"])
    state = run(
        state,
        "inventory.arrange",
        {"order": ["veg", "protein", "carbs"], "moves": [{"id": "protein", "location": "Freezer"}]},
    )
    assert [i["id"] for i in state["inventory"]] == ["veg", "protein", "carbs"]
    assert {i["id"]: i["location"] for i in state["inventory"]} == {
        "veg": "fridge",
        "protein": "freezer",
        "carbs": "fridge",
    }
    # Only where things sit changes, never how much there is.
    assert {i["id"]: i["portions"] for i in state["inventory"]} == {
        i["id"]: i["portions"] for i in before
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"order": ["veg", "protein"]},  # a box left out
        {"order": ["veg", "protein", "carbs", "carbs"]},  # a box twice
        {"order": ["veg", "protein", "carbs"], "moves": [{"id": "missing", "location": "Freezer"}]},
        {"order": ["veg", "protein", "carbs"], "moves": [{"id": "veg", "location": " "}]},
    ],
)
def test_an_arrangement_must_place_every_box_exactly_once(payload):
    with pytest.raises(KitchenError):
        run(fixture_state(), "inventory.arrange", payload)


def test_a_batch_cooked_dish_goes_to_the_freezer_by_default():
    state = fixture_state()
    plan = state["plans"][0]
    task = plan["prep"][0]
    task.pop("outputInventoryId", None)  # a new batch, not a top-up of stock already stored
    state = run(
        state, "prep.status", {"planId": plan["id"], "prepId": task["id"], "status": "completed"}
    )
    output = next(
        i
        for i in state["inventory"]
        if i["id"] == state["plans"][0]["prep"][0]["outputInventoryId"]
    )
    assert output["location"] == "freezer"


def test_a_quick_task_with_nothing_to_make_adds_no_food():
    state = fixture_state()
    plan = state["plans"][0]
    quick = {
        "id": "thaw",
        "name": "Thaw the beef",
        "type": "Other",
        "plannedPortions": 0,
        "actualPortions": 0,
        "activeMinutes": 5,
        "elapsedMinutes": 5,
        "steps": ["Move the beef from the freezer to the fridge the night before."],
        "status": "planned",
        "liked": False,
        "inputs": [],
        "equipment": [],
        "dependencies": [],
    }
    state = run(state, "prep.save", {"planId": plan["id"], "prep": quick})
    items = len(state["inventory"])
    state = run(
        state,
        "prep.status",
        {"planId": plan["id"], "prepId": "thaw", "status": "completed", "actualPortions": 0},
    )
    assert len(state["inventory"]) == items
    assert next(t for t in state["plans"][0]["prep"] if t["id"] == "thaw")["status"] == "completed"


def bought(identifier, name, **extra):
    return {
        "id": identifier,
        "name": name,
        "type": "Protein",
        "portions": 1,
        "location": "Fridge",
        "prepared": False,
        "addedOn": "2026-09-25",
        "priority": False,
        **extra,
    }


def test_what_was_bought_goes_into_the_fridge_once():
    state = fixture_state()
    items = [bought("bought-1", "Chicken mince", portionGrams=500), bought("bought-2", "鸡蛋")]
    state = run(state, "inventory.receive", {"items": items})
    added = [i for i in state["inventory"] if i["id"].startswith("bought-")]
    assert [(i["name"], i["location"], i["prepared"]) for i in added] == [
        ("Chicken mince", "fridge", False),
        ("鸡蛋", "fridge", False),
    ]
    # Receiving the same shopping line again does not double the stock.
    again = run(state, "inventory.receive", {"items": items})
    assert len(again["inventory"]) == len(state["inventory"])
    with pytest.raises(KitchenError):
        run(state, "inventory.receive", {"items": []})


def completed_without_a_box():
    state = fixture_state()
    plan = state["plans"][0]
    task = plan["prep"][0]
    task.pop("outputInventoryId", None)  # a new batch, not a top-up of stock already stored
    before = {i["id"] for i in state["inventory"]}
    state = run(
        state, "prep.status", {"planId": plan["id"], "prepId": task["id"], "status": "completed"}
    )
    return state, plan["id"], task["id"], before


def test_undoing_done_takes_the_new_box_out_of_the_fridge():
    state, plan_id, task_id, before = completed_without_a_box()
    audit = state["audit"][-1]
    assert audit["undo"]["created"] == [f"prep-{task_id}"]
    state = run(state, "change.undo", {"auditId": audit["id"]})
    # No empty box is left behind for a dish that is no longer done.
    assert {i["id"] for i in state["inventory"]} == before
    task = next(t for t in state["plans"][0]["prep"] if t["id"] == task_id)
    assert task["status"] == "planned" and not task.get("outputInventoryId")
    # Doing it again makes the box again.
    state = run(state, "prep.status", {"planId": plan_id, "prepId": task_id, "status": "completed"})
    assert f"prep-{task_id}" in {i["id"] for i in state["inventory"]}


def test_undoing_done_keeps_a_box_that_was_already_there():
    state = fixture_state()
    plan = state["plans"][0]
    task = next(t for t in plan["prep"] if t.get("outputInventoryId"))
    existing = {i["id"] for i in state["inventory"]}
    assert task["outputInventoryId"] in existing
    state = run(
        state, "prep.status", {"planId": plan["id"], "prepId": task["id"], "status": "completed"}
    )
    assert "created" not in (state["audit"][-1]["undo"] or {})
    state = run(state, "change.undo", {"auditId": state["audit"][-1]["id"]})
    assert {i["id"] for i in state["inventory"]} == existing


def test_an_empty_box_refilled_by_prep_goes_to_the_freezer():
    state = fixture_state()
    plan = state["plans"][0]
    task = next(t for t in plan["prep"] if t.get("outputInventoryId"))
    box = next(i for i in state["inventory"] if i["id"] == task["outputInventoryId"])
    box["portions"], box["location"] = 0, "fridge"
    state = run(
        state, "prep.status", {"planId": plan["id"], "prepId": task["id"], "status": "completed"}
    )
    box = next(i for i in state["inventory"] if i["id"] == task["outputInventoryId"])
    assert box["location"] == "freezer"
