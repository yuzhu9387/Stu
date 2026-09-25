"""Regression tests for the production workflow gaps found during service audit."""

import json
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from recipe_agent.api.v1.kitchen_mcp import dispatch
from recipe_agent.domain.kitchen.ai import planning_preferences
from recipe_agent.domain.kitchen.contracts import Meal
from recipe_agent.domain.kitchen.engine import KitchenError, initial_state
from tests.unit.kitchen.compact_fixtures import compact_fixture
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository, plan, recipe
from tests.unit.kitchen.test_engine import fixture_state, run


def test_weekly_prompt_is_persisted_separately_from_a_generated_plan():
    state = run(
        initial_state(), "planning.prompt", {"weekStart": "2026-09-21", "prompt": "优先菠菜"}
    )
    assert state["plans"] == []
    assert state["weeklyPrompts"] == [{"weekStart": "2026-09-21", "prompt": "优先菠菜"}]
    state = run(state, "planning.prompt", {"weekStart": "2026-09-21", "prompt": "No fish"})
    assert state["weeklyPrompts"] == [{"weekStart": "2026-09-21", "prompt": "No fish"}]
    with pytest.raises(ValueError, match="Monday"):
        run(state, "planning.prompt", {"weekStart": "2026-09-22", "prompt": "invalid"})


def test_recipe_time_cannot_have_more_active_than_elapsed_minutes():
    with pytest.raises(ValueError, match="elapsed"):
        run(initial_state(), "recipe.save", {"recipe": {**recipe(), "activeMinutes": 11}})


def test_plan_save_rejects_forged_confirmed_base_from_another_week():
    state = fixture_state()
    candidate = deepcopy(state["plans"][0])
    candidate.update(
        id="later", status="draft", weekStart="2026-09-21", basePlanId="plan", baseVersion=2
    )
    candidate["meals"][0]["day"] = "2026-09-21"
    with pytest.raises(KitchenError, match="same week"):
        run(state, "plan.save", {"plan": candidate})


def test_meal_creation_and_prep_crud_support_manual_planning():
    state = initial_state()
    state = run(state, "recipe.save", {"recipe": recipe()})
    weekly = plan()
    weekly["meals"] = []
    state = run(state, "plan.save", {"plan": weekly})
    meal = plan()["meals"][0]
    state = run(state, "meal.save", {"planId": "plan", "meal": meal})
    # The contract fills defaults the caller omitted, so compare against the
    # validated form rather than the literal that was sent.
    stored = Meal.model_validate(meal).model_dump(mode="json", exclude_none=True)
    assert state["plans"][0]["meals"] == [stored]
    assert stored["included"] is True
    task = {
        "id": "prep",
        "name": "Rice",
        "type": "Carbs",
        "recipeId": "rice",
        "plannedPortions": 3,
        "actualPortions": 0,
        "activeMinutes": 2,
        "elapsedMinutes": 10,
        "steps": ["Cook rice"],
        "status": "planned",
        "liked": False,
        "inputs": [],
        "equipment": [],
        "dependencies": [],
    }
    state = run(state, "prep.save", {"planId": "plan", "prep": task})
    assert state["plans"][0]["prep"][0]["plannedPortions"] == 3
    state = run(state, "prep.delete", {"planId": "plan", "prepId": "prep"})
    assert state["plans"][0]["prep"] == []
    state = run(state, "meal.delete", {"planId": "plan", "mealId": meal["id"]})
    assert state["plans"][0]["meals"] == []


async def test_mcp_invalid_payload_returns_a_tool_error_instead_of_crashing():
    result = await dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "kitchen_command",
                "arguments": {
                    "type": "meal.save",
                    "payload": {},
                    "expectedRevision": 0,
                    "operationId": "bad",
                },
            },
        },
        SimpleNamespace(repository=MemoryRepository(initial_state())),
        "household",
    )
    assert result["result"]["isError"] is True


def test_previous_week_falls_back_to_confirmed_when_execution_is_missing():
    state = initial_state()
    previous = plan()
    previous.update(weekStart="2026-09-14", status="confirmed")
    for meal in previous["meals"]:
        meal["day"] = str(date.fromisoformat(meal["day"]) - timedelta(days=7))
    state.update(recipes=[recipe()], plans=[previous])
    result = planning_preferences(state, date(2026, 9, 21))
    assert result["previousWeek"]["historySource"] == "confirmed-plan"
    assert result["previousWeek"]["historyIncomplete"] is True
    assert result["previousWeek"]["recipeCounts"] == {"rice": 21}
    assert result["previousWeek"]["completedMeals"] == []


def test_liked_combination_does_not_assign_likes_to_every_component_recipe():
    state = initial_state()
    other = {**recipe(), "id": "veg", "liked": False}
    previous = plan()
    previous["meals"] = [previous["meals"][0]]
    previous["meals"][0]["liked"] = True
    previous["meals"][0]["components"].append(
        {"id": "veg-c", "recipeId": "veg", "name": "Veg", "type": "Vegetables", "portions": 3}
    )
    state.update(recipes=[recipe(), other], plans=[previous])
    result = planning_preferences(state, date(2026, 9, 28))
    assert all(row["likedMealCount"] == 0 for row in result["rankedRecipes"])
    assert result["likedCombinations"] == [{"recipeIds": ["rice", "veg"], "count": 1}]


def test_tag_batch_apply_and_remove_are_atomic():
    state = run(initial_state(), "recipe.save", {"recipe": recipe()})
    state = run(state, "recipe.save", {"recipe": {**recipe(), "id": "second"}})
    state = run(state, "tag.apply", {"recipeIds": ["rice", "second"], "name": "宝宝饭"})
    assert all(r["tags"] == ["宝宝饭"] for r in state["recipes"])
    with pytest.raises(KitchenError):
        run(state, "tag.apply", {"recipeIds": ["rice", "missing"], "name": "No partial save"})
    assert state["recipes"][0]["tags"] == ["宝宝饭"]
    state = run(state, "tag.apply", {"recipeIds": ["rice"], "name": "宝宝饭", "remove": True})
    assert state["recipes"][0]["tags"] == []
    assert state["recipes"][1]["tags"] == ["宝宝饭"]


def test_leftovers_require_completion_bound_amount_and_block_unsafe_completion_undo():
    state = fixture_state()
    with pytest.raises(KitchenError, match="after completing"):
        run(
            state,
            "meal.leftovers",
            {"planId": "plan", "mealId": "meal", "componentId": "carbs", "portions": 1},
        )
    state = run(state, "prep.status", {"planId": "plan", "prepId": "prep", "status": "completed"})
    state = run(state, "meal.status", {"planId": "plan", "mealId": "meal", "status": "completed"})
    completed_audit = state["audit"][-1]["id"]
    state = run(
        state,
        "meal.leftovers",
        {
            "planId": "plan",
            "mealId": "meal",
            "componentId": "carbs",
            "portions": 1,
            "location": "freezer",
        },
    )
    leftover_audit = state["audit"][-1]["id"]
    assert state["inventory"][-1]["portions"] == 1
    assert state["inventory"][-1]["location"] == "freezer"
    with pytest.raises(KitchenError, match="exceed"):
        run(
            state,
            "meal.leftovers",
            {"planId": "plan", "mealId": "meal", "componentId": "carbs", "portions": 3},
        )
    with pytest.raises(KitchenError, match="leftovers"):
        run(state, "change.undo", {"auditId": completed_audit})
    state = run(state, "change.undo", {"auditId": leftover_audit})
    state = run(state, "change.undo", {"auditId": completed_audit})
    # Undoing the leftovers took their box away too: no empty box is left behind.
    assert [i["portions"] for i in state["inventory"]] == [5, 6, 4]


async def test_generation_keeps_a_draft_whose_stock_runs_short():
    from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    state["recipes"] = [recipe()]
    state["inventory"] = [
        {
            "id": "stock",
            "name": "Rice",
            "type": "Carbs",
            "portions": 2,
            "prepared": True,
            "location": "fridge",
            "addedOn": "2026-09-17",
            "priority": False,
            "recipeId": "rice",
        }
    ]
    proposed = plan()
    proposed["meals"][0]["components"][0]["inventoryId"] = "stock"
    repository = MemoryRepository(state)
    ai = KitchenAI(
        repository, None, FakeProvider({"recipes": [], "plan": proposed}), compact_weekly=False
    )
    # The shortage is prepared on prep day, as when the household confirms.
    result = await ai.generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="supply"),
    )
    saved = result["state"]["plans"][0]["meals"][0]["components"][0]
    assert saved["inventoryId"] == "stock"


def test_planning_stock_projection_separates_on_hand_and_reserved_portions():
    from recipe_agent.domain.kitchen.ai import projected_inventory

    state = fixture_state()
    projected = projected_inventory(state, "2026-09-21")
    quantities = {item["inventoryId"]: item for item in projected}
    assert quantities["protein"]["onHandPortions"] == 2
    assert quantities["protein"]["plannedOutputPortions"] == 3
    assert quantities["protein"]["reservedPortions"] == 3
    assert quantities["protein"]["projectedPortions"] == 2
    assert quantities["carbs"]["projectedPortions"] == 3
    assert quantities["veg"]["projectedPortions"] == 1


async def test_chat_replacement_reconciles_orphan_prep_in_preview():
    from recipe_agent.domain.kitchen.ai import ChatRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    state["recipes"] = [recipe()]
    weekly = plan()
    weekly["meals"] = [weekly["meals"][0]]
    weekly["meals"][0]["components"][0]["prepId"] = "batch"
    weekly["prep"] = [
        {
            "id": "batch",
            "name": "Rice",
            "type": "Carbs",
            "recipeId": "rice",
            "plannedPortions": 3,
            "actualPortions": 0,
            "activeMinutes": 2,
            "elapsedMinutes": 10,
            "steps": ["Cook rice"],
            "status": "planned",
            "liked": False,
            "inputs": [],
            "equipment": [],
            "dependencies": [],
        }
    ]
    state["plans"] = [weekly]
    replacement = deepcopy(weekly["meals"][0])
    replacement["components"][0].pop("prepId")
    repository = MemoryRepository(state)
    ai = KitchenAI(
        repository,
        None,
        FakeProvider(
            {"reply": "Cook it fresh", "meals": [replacement], "needsClarification": False}
        ),
        compact_weekly=False,
    )
    result = await ai.chat(
        "scope",
        ChatRequest(
            planId="plan",
            mealIds=[replacement["id"]],
            message="Cook fresh instead",
            expectedRevision=0,
        ),
    )
    assert result["prep"] == []
    assert repository.state["plans"][0]["prep"] == weekly["prep"]


async def test_chat_without_a_named_scope_acts_on_the_whole_week():
    # "Which meals should change?" was asked on every message that named none.
    # Stu now acts: the whole week is in scope and the model is called.
    from recipe_agent.domain.kitchen.ai import ChatRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    state["plans"] = [plan()]
    state["recipes"] = [recipe()]
    repository = MemoryRepository(state)
    provider = FakeProvider(
        {"reply": "Nothing needed changing", "meals": [], "needsClarification": False}
    )
    result = await KitchenAI(repository, None, provider, compact_weekly=False).chat(
        "scope", ChatRequest(planId="plan", message="Make it different", expectedRevision=0)
    )
    assert result["needsClarification"] is False
    payload = json.loads(provider.requests[0][0][1]["content"])
    assert payload["wholeWeek"] is True
    assert set(payload["editableIds"]) == {m["id"] for m in plan()["meals"]}
    assert repository.state["plans"][0]["chat"][0]["text"] == "Make it different"


def test_editing_one_meal_recomputes_prep_and_undo_restores_batch():
    state = initial_state()
    state = run(state, "recipe.save", {"recipe": recipe()})
    weekly = plan()
    weekly["meals"] = [weekly["meals"][0]]
    weekly["meals"][0]["components"][0]["prepId"] = "batch"
    weekly["prep"] = [
        {
            "id": "batch",
            "name": "Rice",
            "type": "Carbs",
            "recipeId": "rice",
            "plannedPortions": 3,
            "actualPortions": 0,
            "activeMinutes": 2,
            "elapsedMinutes": 10,
            "steps": ["Cook rice"],
            "status": "planned",
            "liked": False,
            "inputs": [],
            "equipment": [],
            "dependencies": [],
        }
    ]
    state = run(state, "plan.save", {"plan": weekly})
    meal = deepcopy(weekly["meals"][0])
    meal["components"][0].pop("prepId")
    state = run(state, "meal.save", {"planId": "plan", "meal": meal})
    assert state["plans"][0]["prep"] == []
    saved = state["audit"][-1]["id"]
    state = run(state, "change.undo", {"auditId": saved})
    assert state["plans"][0]["prep"] == weekly["prep"]
    assert state["plans"][0]["meals"][0]["components"][0]["prepId"] == "batch"


def test_prep_scheduler_uses_waiting_time_before_a_busy_equipment_task():
    from recipe_agent.domain.kitchen.scheduling import schedule_tasks

    result = schedule_tasks(
        [
            {"id": "a", "activeMinutes": 10, "elapsedMinutes": 90, "equipment": ["oven"]},
            {"id": "b", "activeMinutes": 10, "elapsedMinutes": 20, "equipment": ["oven"]},
            {"id": "c", "activeMinutes": 10, "elapsedMinutes": 90, "equipment": ["pot"]},
        ]
    )
    assert result["activeMinutes"] == 30
    assert result["elapsedMinutes"] == 110
    assert {row["id"]: row["startMinutes"] for row in result["tasks"]} == {"a": 0, "c": 10, "b": 90}


async def test_generation_namespaces_prep_batches_to_avoid_future_week_collisions():
    from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    proposed = plan()
    proposed["prep"] = [
        {
            "id": "rice-batch",
            "name": "Rice",
            "type": "Carbs",
            "recipeId": "rice",
            "plannedPortions": 3,
            "actualPortions": 0,
            "activeMinutes": 2,
            "elapsedMinutes": 10,
            "steps": ["Cook rice"],
            "status": "planned",
            "liked": False,
            "inputs": [],
            "equipment": [],
            "dependencies": [],
        }
    ]
    proposed["meals"][0]["components"][0]["prepId"] = "rice-batch"
    provider = FakeProvider(compact_fixture({"recipes": [recipe()], "plan": proposed}))
    repository = MemoryRepository(initial_state())
    ai = KitchenAI(repository, None, provider, compact_weekly=False)
    first = await ai.generate(
        "household",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="first-week"),
    )
    first_plan = first["state"]["plans"][0]
    assert first_plan["prep"][0]["id"] != "rice-batch"
    assert first_plan["meals"][0]["components"][0]["prepId"] == first_plan["prep"][0]["id"]
    provider.result = {"recipes": [], "plan": proposed}
    for meal in provider.result["plan"]["meals"]:
        meal["day"] = str(date.fromisoformat(meal["day"]) + timedelta(days=7))
    provider.result["plan"]["weekStart"] = "2026-09-28"
    provider.result["recipes"] = []
    second = await ai.generate(
        "household",
        GenerateRequest(weekStart="2026-09-28", expectedRevision=1, operationId="second-week"),
    )
    second_plan = second["state"]["plans"][1]
    assert second_plan["prep"][0]["id"] != first_plan["prep"][0]["id"]


async def test_meals_named_in_the_message_win_over_selected_cards():
    # The message is the latest word, so it sets the scope instead of a question.
    from recipe_agent.domain.kitchen.ai import ChatRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    state.update(recipes=[recipe()], plans=[plan()])
    repository = MemoryRepository(state)
    provider = FakeProvider({"reply": "Done", "meals": [], "needsClarification": False})
    await KitchenAI(repository, None, provider, compact_weekly=False).chat(
        "scope",
        ChatRequest(
            planId="plan", mealIds=["m0dinner"], message="Change all breakfasts", expectedRevision=0
        ),
    )
    payload = json.loads(provider.requests[0][0][1]["content"])
    breakfasts = {m["id"] for m in plan()["meals"] if m["slot"] == "breakfast"}
    assert set(payload["editableIds"]) == breakfasts


async def test_an_answer_to_stus_question_gets_an_action_not_another_question():
    from recipe_agent.domain.kitchen.ai import ChatRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    state.update(recipes=[recipe()], plans=[plan()])
    provider = FakeProvider(
        {"reply": "More fish?", "meals": [], "needsClarification": True, "options": ["Yes", "No"]}
    )
    result = await KitchenAI(MemoryRepository(state), None, provider, compact_weekly=False).chat(
        "scope",
        ChatRequest(
            planId="plan", message="Lighter", answeringClarification=True, expectedRevision=0
        ),
    )
    assert result["needsClarification"] is False
    assert result["options"] == []
    assert json.loads(provider.requests[0][0][1]["content"])["answeringClarification"] is True


async def test_a_new_dish_is_kept_with_an_analysis_warning():
    # A fresh dish without a saved recipe is usable and can be edited later.
    from recipe_agent.domain.kitchen.ai import ChatRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    state.update(recipes=[recipe()], plans=[plan()])
    loose = deepcopy(plan()["meals"][0])
    loose["components"] = [{"id": "milk", "name": "牛奶", "type": "Dairy", "portions": 1}]
    provider = FakeProvider({"reply": "Add milk", "meals": [loose], "needsClarification": False})
    repository = MemoryRepository(state)
    result = await KitchenAI(repository, None, provider, compact_weekly=False).chat(
        "scope",
        ChatRequest(planId="plan", mealIds=[loose["id"]], message="Add milk", expectedRevision=0),
    )
    assert len(provider.requests) == 1
    assert result["meals"][0]["components"][0]["name"] == "牛奶"
    assert any(v["kind"] == "recipe" for v in result["violations"])
    assert repository.state["plans"][0]["chat"][-1]["text"] == result["reply"]


async def test_generated_plan_preserves_enabled_guidance_versions_when_settings_change():
    from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider

    state = initial_state()
    enabled = {
        "id": "rule",
        "title": "Vegetables",
        "content": "Offer vegetables daily",
        "enabled": True,
        "version": 2,
    }
    state["settings"]["guidance"] = [enabled, {**enabled, "id": "off", "enabled": False}]
    repository = MemoryRepository(state)
    result = await KitchenAI(
        repository,
        None,
        FakeProvider(compact_fixture({"recipes": [recipe()], "plan": plan()})),
        compact_weekly=False,
    ).generate(
        "scope", GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="guidance")
    )
    assert result["state"]["plans"][0]["guidanceSnapshot"] == [enabled]
    settings = deepcopy(result["state"]["settings"])
    settings["guidance"][0].update(content="New version", version=3)
    updated = run(result["state"], "settings.save", {"settings": settings})
    assert updated["plans"][0]["guidanceSnapshot"] == [enabled]
