import pytest

from recipe_agent.domain.kitchen.engine import KitchenError, initial_state

from .test_engine import fixture_state, run


def test_workflow_preserves_prompt_and_confirmation_advances_atomically():
    state = fixture_state()
    state["plans"][0]["status"] = "draft"
    week = state["plans"][0]["weekStart"]
    state = run(state, "planning.prompt", {"weekStart": week, "prompt": "Use carrots"})
    state = run(
        state,
        "planning.workflow",
        {
            "weekStart": week,
            "workflow": {"planId": "plan", "step": "preferences", "focus": "shopping"},
        },
    )
    state = run(state, "planning.prompt", {"weekStart": week, "prompt": "Use broccoli"})
    assert state["weeklyPrompts"][0]["workflow"]["step"] == "preferences"
    state = run(state, "plan.confirm", {"id": "plan"})
    assert state["weeklyPrompts"][0] == {
        "weekStart": week,
        "prompt": "Use broccoli",
        "workflow": {"planId": "plan", "step": "shopping", "focus": "shopping"},
    }


def test_cannot_open_shopping_for_a_draft_or_mismatched_week():
    state = fixture_state()
    state["plans"][0]["status"] = "draft"
    for week, step in [("2026-09-14", "shopping"), ("2026-09-21", "adjust")]:
        with pytest.raises(KitchenError):
            run(
                state,
                "planning.workflow",
                {
                    "weekStart": week,
                    "workflow": {"planId": "plan", "step": step, "focus": "shopping"},
                },
            )


def test_shopping_checks_persist_and_do_not_change_inventory_or_plan_version():
    state = fixture_state()
    before_stock, version = state["inventory"], state["plans"][0]["version"]
    state = run(state, "shopping.check", {"planId": "plan", "key": "鸡肉|g|300", "checked": True})
    assert state["plans"][0]["shoppingChecked"] == ["鸡肉|g|300"]
    assert state["plans"][0]["version"] == version
    assert state["inventory"] == before_stock
    state = run(state, "shopping.check", {"planId": "plan", "key": "鸡肉|g|300", "checked": False})
    assert state["plans"][0]["shoppingChecked"] == []


def test_mark_all_picked_up_checks_every_item_at_once_and_can_be_cleared():
    state = fixture_state()
    state = run(state, "shopping.check", {"planId": "plan", "key": "鸡肉|g|300", "checked": True})
    everything = ["鸡肉|g|300", "米|g|200", "西兰花|g|150", "米|g|200"]
    state = run(state, "shopping.check", {"planId": "plan", "keys": everything, "checked": True})
    assert state["plans"][0]["shoppingChecked"] == ["鸡肉|g|300", "米|g|200", "西兰花|g|150"]
    state = run(state, "shopping.check", {"planId": "plan", "keys": everything, "checked": False})
    assert state["plans"][0]["shoppingChecked"] == []
    for bad in ([], ["ok", ""], "not-a-list"):
        with pytest.raises(KitchenError):
            run(state, "shopping.check", {"planId": "plan", "keys": bad, "checked": True})


def test_preferences_before_a_plan_can_remember_their_step():
    state = run(
        initial_state(),
        "planning.workflow",
        {"weekStart": "2026-09-21", "workflow": {"step": "preferences", "focus": "shopping"}},
    )
    assert state["weeklyPrompts"][0]["workflow"]["step"] == "preferences"
