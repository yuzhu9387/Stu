"""Planning preferences warn without discarding a usable AI answer."""

from copy import deepcopy

import pytest

from recipe_agent.domain.kitchen.ai import ChatRequest, GenerateRequest, KitchenAI
from recipe_agent.domain.kitchen.engine import KitchenError
from recipe_agent.domain.kitchen.scheduling import plan_rule_violations
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository, plan, recipe
from tests.unit.kitchen.test_ai_variety import SequenceProvider, variety_state, with_dish
from tests.unit.kitchen.test_engine import run


@pytest.mark.parametrize("problem", ["new-dish", "repeat", "time"])
async def test_chat_keeps_usable_changes_and_reports_rules(problem):
    state = variety_state()
    current = plan()
    current["meals"][0] = with_dish(current["meals"][0])
    state["plans"] = [current]
    meal = deepcopy(current["meals"][5])
    expected = {"new-dish": "recipe", "repeat": "repeat", "time": "daily"}[problem]
    if problem == "new-dish":
        meal["components"] = [
            {"id": "salad", "name": "简单生蔬菜拼盘", "type": "Vegetables", "portions": 3}
        ]
    elif problem == "repeat":
        meal = with_dish(meal)
    else:
        meal.update(activeMinutes=90, elapsedMinutes=90)
    provider = SequenceProvider({"reply": "已调整", "meals": [meal], "needsClarification": False})
    result = await KitchenAI(MemoryRepository(state), None, provider).propose(
        state,
        ChatRequest(planId="plan", mealIds=[meal["id"]], message="调整这一餐", expectedRevision=0),
    )
    assert len(result["meals"]) == 1
    assert len(provider.requests) == 1
    candidate = deepcopy(current)
    candidate["meals"][5] = result["meals"][0]
    saved = run(state, "plan.save", {"plan": candidate})
    confirmed = run(saved, "plan.confirm", {"id": "plan"})
    assert expected in {v["kind"] for v in plan_rule_violations(confirmed, confirmed["plans"][0])}


async def test_generation_keeps_a_repeated_over_budget_week_without_retrying():
    state = variety_state()
    current = plan()
    current["meals"][0] = with_dish(current["meals"][0])
    current["meals"][5] = with_dish(current["meals"][5])
    current["meals"][5].update(activeMinutes=90, elapsedMinutes=90)
    provider = SequenceProvider({"recipes": [], "plan": current})
    result = await KitchenAI(
        MemoryRepository(state), None, provider, compact_weekly=False
    ).generate(
        "scope",
        GenerateRequest(weekStart=current["weekStart"], expectedRevision=0, operationId="advisory"),
    )
    assert len(provider.requests) == 1
    assert {"repeat", "daily"} <= {
        v["kind"] for v in plan_rule_violations(result["state"], result["state"]["plans"][0])
    }


async def test_current_menu_and_rules_are_context_in_system_prompt():
    state = variety_state()
    state["plans"] = [plan()]
    provider = SequenceProvider({"reply": "OK", "meals": [], "needsClarification": False})
    await KitchenAI(MemoryRepository(state), None, provider).propose(
        state, ChatRequest(planId="plan", message="少点米饭", expectedRevision=0)
    )
    system = "\n".join(m["content"] for m in provider.requests[0] if m["role"] == "system")
    assert "maxDailyActiveMinutes" in system
    assert "m0breakfast" in system
    assert "context data" in system
    assert "analysis" in system.lower()


def test_new_recipe_can_be_saved_and_linked_to_its_meal_atomically():
    state = variety_state()
    state["plans"] = [plan()]
    meal = deepcopy(state["plans"][0]["meals"][0])
    new = {**recipe(), "id": "new", "name": "New dish"}
    meal["components"][0].update(recipeId="new", name="New dish")
    saved = run(state, "meal.save", {"planId": "plan", "meal": meal, "recipes": [new]})
    assert any(r["id"] == "new" for r in saved["recipes"])
    assert saved["plans"][0]["meals"][0]["components"][0]["recipeId"] == "new"


@pytest.mark.parametrize("in_steps", [False, True])
async def test_recipe_less_dishes_still_respect_known_allergies(in_steps):
    state = variety_state()
    state["settings"]["allergies"] = ["peanut"]
    state["plans"] = [plan()]
    meal = deepcopy(state["plans"][0]["meals"][0])
    meal["components"] = [
        {
            "id": "salad",
            "name": "Salad" if in_steps else "Peanut salad",
            "type": "Vegetables",
            "portions": 3,
        }
    ]
    meal["steps"] = ["Mix in peanuts." if in_steps else "Mix and serve."]
    proposal = {"reply": "Changed", "meals": [meal], "needsClarification": False}
    provider = SequenceProvider(proposal, proposal, proposal)
    result = await KitchenAI(MemoryRepository(state), None, provider).propose(
        state,
        ChatRequest(
            planId="plan", mealIds=[meal["id"]], message="Change this meal", expectedRevision=0
        ),
    )
    assert result["meals"] == []
    assert "allergy" in result["reply"]
    state["plans"][0]["meals"][0] = meal
    with pytest.raises(KitchenError, match=r"[Aa]llergy"):
        run(state, "plan.confirm", {"id": "plan"})
