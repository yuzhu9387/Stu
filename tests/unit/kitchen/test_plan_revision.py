"""Editing a confirmed week works on a copy, while the calendar keeps the
confirmed version: meals marked done, skipped or changed there (and prep done,
likes, undo) follow into the copy, so the edit can still be saved and
confirmed. Changing what a meal is on the calendar still needs the edit to be
reconciled."""

import pytest

from recipe_agent.domain.kitchen.engine import KitchenError, find

from .test_dish_baskets import WEEK, household, portions, run
from .test_prep_from_fridge import fridge_prep


def dinner(**extra):
    return {
        "id": "dinner",
        "day": WEEK,
        "slot": "dinner",
        "components": [{"id": "rice", "name": "米饭", "type": "Carbs", "portions": 1}],
        "activeMinutes": 5,
        "elapsedMinutes": 10,
        "steps": ["煮"],
        "status": "planned",
        "liked": False,
        "locked": False,
        **extra,
    }


def editing(state=None):
    """The week confirmed, then opened for editing as a copy."""
    state = state or household()
    state = run(state, "meal.save", {"planId": "plan", "meal": dinner()})
    state = run(state, "plan.confirm", {"id": "plan"})
    base = plans(state)["plan"]
    revision = {**base, "id": "rev", "status": "draft", "basePlanId": "plan"}
    return run(state, "plan.save", {"plan": {**revision, "baseVersion": base["version"]}})


def plans(state):
    return {plan["id"]: plan for plan in state["plans"]}


def noodles():
    return dinner(components=[{"id": "noodles", "name": "面条", "type": "Carbs", "portions": 1}])


def test_a_meal_done_on_the_calendar_follows_into_the_edit_which_still_confirms():
    state = run(editing(), "meal.save", {"planId": "rev", "meal": noodles()})
    state = run(state, "meal.status", {"planId": "plan", "mealId": "lunch", "status": "completed"})
    base, edit = plans(state)["plan"], plans(state)["rev"]
    assert edit["baseVersion"] == base["version"]
    assert find(edit["meals"], "lunch")["status"] == "completed"
    assert find(edit["meals"], "dinner")["components"][0]["name"] == "面条"
    eaten = portions(state)
    state = run(state, "plan.save", {"plan": plans(state)["rev"]})
    state = run(state, "plan.confirm", {"id": "rev"})
    assert (plans(state)["rev"]["status"], plans(state)["plan"]["status"]) == ("confirmed", "draft")
    assert find(plans(state)["rev"]["meals"], "lunch")["status"] == "completed"
    assert portions(state) == eaten


def test_a_meal_eaten_as_first_planned_replaces_its_edit():
    changed = {
        **find(plans(editing())["rev"]["meals"], "lunch"),
        "components": noodles()["components"],
    }
    state = run(editing(), "meal.save", {"planId": "rev", "meal": changed})
    state = run(
        state,
        "meal.status",
        {"planId": "plan", "mealId": "lunch", "status": "changed", "note": "外卖"},
    )
    lunch = find(plans(state)["rev"]["meals"], "lunch")
    assert lunch == find(plans(state)["plan"]["meals"], "lunch")
    assert (lunch["status"], lunch["note"]) == ("changed", "外卖")
    run(state, "plan.confirm", {"id": "rev"})


def test_undo_on_the_calendar_follows_into_the_edit():
    state = run(
        editing(), "meal.status", {"planId": "plan", "mealId": "lunch", "status": "completed"}
    )
    state = run(state, "change.undo", {"auditId": state["audit"][-1]["id"]})
    base, edit = plans(state)["plan"], plans(state)["rev"]
    assert find(edit["meals"], "lunch")["status"] == "planned"
    assert edit["baseVersion"] == base["version"]
    run(state, "plan.confirm", {"id": "rev"})


def test_prep_done_and_likes_on_the_calendar_follow_into_the_edit():
    state = run(household(), "prep.save", {"planId": "plan", "prep": fridge_prep()})
    state = editing(state)
    state = run(
        state,
        "prep.status",
        {"planId": "plan", "prepId": "egg-pancakes", "status": "completed", "actualPortions": 2},
    )
    state = run(state, "meal.like", {"planId": "plan", "mealId": "lunch", "liked": True})
    edit = plans(state)["rev"]
    assert find(edit["prep"], "egg-pancakes")["status"] == "completed"
    assert find(edit["meals"], "lunch")["liked"] is True
    assert edit["baseVersion"] == plans(state)["plan"]["version"]
    run(state, "plan.confirm", {"id": "rev"})


def test_changing_what_a_meal_is_on_the_calendar_still_needs_the_edit_reconciled():
    state = run(editing(), "meal.save", {"planId": "plan", "meal": noodles()})
    assert plans(state)["rev"]["baseVersion"] != plans(state)["plan"]["version"]
    with pytest.raises(KitchenError, match="Confirmed plan changed"):
        run(state, "plan.confirm", {"id": "rev"})
