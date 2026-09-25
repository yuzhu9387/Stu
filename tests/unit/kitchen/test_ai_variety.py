"""AI bootstrap and dish rotation are enforced before workspace mutation."""

import json
from copy import deepcopy

import pytest

from recipe_agent.domain.kitchen.ai import ChatRequest, GenerateRequest, KitchenAI
from recipe_agent.domain.kitchen.engine import initial_state
from recipe_agent.domain.kitchen.scheduling import plan_rule_violations, validate_plan_timing
from tests.unit.kitchen.compact_fixtures import compact_fixture
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository, plan, recipe


def dish(identifier="chicken", name="Chicken meatballs"):
    return {
        **recipe(),
        "id": identifier,
        "name": name,
        "type": "Protein",
        "mealTypes": ["breakfast", "lunch", "dinner"],
        "ingredients": [{"name": "Chicken", "quantity": 300, "unit": "g"}],
    }


def with_dish(meal, identifier="chicken", name="Chicken meatballs"):
    result = deepcopy(meal)
    result["components"][0].update(recipeId=identifier, name=name, type="Protein")
    return result


def variety_state():
    state = initial_state()
    state["recipes"] = [recipe(), dish()]
    return state


@pytest.mark.parametrize("day", [1])
def test_repeated_dish_needs_one_intervening_day(day):
    state = variety_state()
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][day * 3 + 2] = with_dish(candidate["meals"][day * 3 + 2])
    with pytest.raises(ValueError, match="repeat"):
        validate_plan_timing(state, candidate)


def test_dish_can_return_on_wednesday_and_plain_rice_can_repeat():
    state = variety_state()
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][8] = with_dish(candidate["meals"][8])
    assert len(validate_plan_timing(state, candidate)["meals"]) == 21


def test_repeat_gap_can_be_configured_to_two_intervening_days():
    state = variety_state()
    state["settings"]["recipeRepeatGapDays"] = 2
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][8] = with_dish(candidate["meals"][8])
    with pytest.raises(ValueError, match="repeat"):
        validate_plan_timing(state, candidate)


def test_repeat_detected_across_different_recipe_ids_and_bilingual_aliases():
    state = variety_state()
    state["recipes"] += [dish("clone", "鸡肉丸 (Chicken Meatballs)")]
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][5] = with_dish(candidate["meals"][5], "clone", "鸡肉丸")
    with pytest.raises(ValueError, match="repeat"):
        validate_plan_timing(state, candidate)


def test_prior_sunday_confirmed_meal_blocks_monday_even_with_partial_execution_history():
    state = variety_state()
    previous = plan()
    previous.update(id="previous", weekStart="2026-09-14", status="confirmed")
    for meal in previous["meals"]:
        meal["day"] = (
            meal["day"]
            .replace("-21", "-14")
            .replace("-22", "-15")
            .replace("-23", "-16")
            .replace("-24", "-17")
            .replace("-25", "-18")
            .replace("-26", "-19")
            .replace("-27", "-20")
        )
    previous["meals"][0]["status"] = "completed"
    previous["meals"][-1] = with_dish(previous["meals"][-1])
    state["plans"] = [previous]
    candidate = plan()
    candidate["meals"][2] = with_dish(candidate["meals"][2])
    with pytest.raises(ValueError, match="repeat"):
        validate_plan_timing(state, candidate)
    previous["meals"][-1]["status"] = "skipped"
    validate_plan_timing(state, candidate)


class SequenceProvider:
    def __init__(self, *outputs):
        self.outputs = outputs
        self.requests = []

    async def complete(self, messages, schema, *, vision=False):
        self.requests.append(deepcopy(messages))
        return deepcopy(self.outputs[min(len(self.requests) - 1, len(self.outputs) - 1)])


def bootstrap_result():
    candidate = plan()
    recipes = [
        dish(f"dish-{i}", name)
        for i, name in enumerate(
            [
                "Chicken meatballs",
                "Salmon couscous",
                "Tofu noodle soup",
                "Lentil pasta",
                "Vegetable omelette",
                "Banana oatmeal",
                "Yogurt fruit bowl",
                "Beef broccoli",
                "Pumpkin soup",
            ]
        )
    ]
    # Each dish appears once per three days (Monday then Thursday then Sunday).
    for i, meal in enumerate(candidate["meals"]):
        selected = recipes[i % 9]
        candidate["meals"][i] = with_dish(meal, selected["id"], selected["name"])
    return {"recipes": recipes, "plan": candidate}


async def test_empty_library_bootstraps_complete_recipes_atomically_despite_weekly_limit():
    repo = MemoryRepository(initial_state())
    provider = SequenceProvider(compact_fixture(bootstrap_result()))
    ai = KitchenAI(repo, None, provider, compact_weekly=False)
    result = await ai.generate(
        "scope",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="bootstrap"),
    )
    assert len(result["state"]["recipes"]) == 9
    assert len(result["state"]["plans"][0]["meals"]) == 21
    assert result["state"]["revision"] == 1
    context = json.loads(provider.requests[0][1]["content"])
    assert context["recipeGeneration"]["mode"] == "bootstrap"
    assert context["recipeGeneration"]["maxNewRecipes"] == 21
    await ai.generate(
        "scope",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="bootstrap"),
    )
    assert len(repo.state["recipes"]) == 9
    assert len(provider.requests) == 1


def every_breakfast_the_same(result):
    """A repeat no reordering of days can fix, so the model has to repair it."""
    bad = deepcopy(result)
    for index in range(0, 21, 3):
        bad["plan"]["meals"][index] = with_dish(bad["plan"]["meals"][index], "dish-0")
    return bad


async def test_invalid_generation_repaired_before_any_mutation():
    valid = bootstrap_result()
    bad = compact_fixture(valid)
    bad["days"][0]["breakfast"] = "missing-template"
    provider = SequenceProvider(bad, compact_fixture(valid))
    repo = MemoryRepository(initial_state())
    result = await KitchenAI(repo, None, provider, compact_weekly=False).generate(
        "scope", GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="repair")
    )
    assert len(provider.requests) == 2
    assert result["state"]["revision"] == 1
    assert result["state"]["plans"][0]["meals"][3]["components"][0]["recipeId"] == "dish-3"
    assert "template" in provider.requests[-1][-1]["content"].lower()


async def test_failed_repairs_leave_recipes_and_plans_unchanged():
    bad = compact_fixture(bootstrap_result())
    bad["days"][0]["breakfast"] = "missing-template"
    provider = SequenceProvider(bad)
    repo = MemoryRepository(initial_state())
    with pytest.raises(ValueError, match="template"):
        await KitchenAI(repo, None, provider, compact_weekly=False).generate(
            "scope", GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="bad")
        )
    assert repo.state["revision"] == 0
    assert repo.state["recipes"] == []
    assert repo.state["plans"] == []
    assert len(provider.requests) == 2


async def test_chat_warns_about_repeat_in_an_unselected_neighbour():
    state = variety_state()
    current = plan()
    current["meals"][0] = with_dish(current["meals"][0])
    state["plans"] = [current]
    replacement = with_dish(current["meals"][5])
    provider = SequenceProvider(
        {"reply": "Try chicken", "meals": [replacement], "needsClarification": False}
    )
    repo = MemoryRepository(state)
    refused = await KitchenAI(repo, None, provider, compact_weekly=False).chat(
        "scope",
        ChatRequest(
            planId="plan",
            message="Change Tuesday dinner",
            mealIds=[replacement["id"]],
            expectedRevision=0,
        ),
    )
    assert refused["meals"][0]["id"] == replacement["id"]
    assert any(v["kind"] == "repeat" for v in refused["violations"])
    # Only the conversation was recorded; applying is still a separate action.
    assert repo.state["plans"][0]["meals"][5]["components"] == current["meals"][5]["components"]
    assert len(provider.requests) == 1


def test_same_day_leftovers_are_allowed_but_inventory_recipe_blocks_next_day():
    state = variety_state()
    state["inventory"] = [
        {"id": "batch", "name": "Leftover batch", "recipeId": "chicken", "prepared": True}
    ]
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][2] = with_dish(candidate["meals"][2])
    validate_plan_timing(state, candidate)
    component = candidate["meals"][5]["components"][0]
    component.pop("recipeId")
    component.update(inventoryId="batch", name="Stored dinner")
    with pytest.raises(ValueError, match="repeat"):
        validate_plan_timing(state, candidate)


async def test_established_library_uses_new_recipe_limit_as_guidance():
    state = initial_state()
    state["recipes"] = [recipe()]
    repo = MemoryRepository(state)
    provider = SequenceProvider(bootstrap_result())
    await KitchenAI(repo, None, provider, compact_weekly=False).generate(
        "scope", GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="weekly")
    )
    assert len(repo.state["recipes"]) == 10
    assert len(repo.state["plans"]) == 1
    assert len(provider.requests) == 1


async def test_incomplete_library_bootstraps_without_overwriting_original_recipe():
    state = initial_state()
    state["recipes"] = [{**recipe(), "incomplete": True, "ingredients": []}]
    repo = MemoryRepository(state)
    result = await KitchenAI(
        repo, None, SequenceProvider(compact_fixture(bootstrap_result())), compact_weekly=False
    ).generate(
        "scope",
        GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="incomplete"),
    )
    assert len(result["state"]["recipes"]) == 10
    assert result["state"]["recipes"][0]["incomplete"] is True


async def test_chat_uses_enabled_current_knowledge_and_does_not_replay_disabled_snapshot():
    state = variety_state()
    current = plan()
    state["plans"] = [current]
    enabled = {
        "id": "current",
        "title": "Current guidance",
        "content": "Current fact",
        "enabled": True,
        "version": 2,
    }
    disabled = {
        "id": "old",
        "title": "Old guidance",
        "content": "DISABLED_KNOWLEDGE_CONTENT",
        "enabled": False,
        "version": 3,
    }
    state["knowledgeDocuments"] = [enabled, disabled]
    current["knowledgeSnapshot"] = [{**disabled, "enabled": True, "version": 1}]

    class CaptureProvider:
        async def complete(self, messages, schema, *, vision=False):
            context = json.loads(messages[1]["content"])
            assert context["knowledgeDocuments"] == [enabled]
            assert "DISABLED_KNOWLEDGE_CONTENT" not in messages[1]["content"]
            raise RuntimeError("captured current knowledge")

    with pytest.raises(RuntimeError, match="captured current knowledge"):
        await KitchenAI(
            MemoryRepository(state), None, CaptureProvider(), compact_weekly=False
        ).chat(
            "scope",
            ChatRequest(
                planId="plan",
                message="Change this",
                mealIds=[current["meals"][0]["id"]],
                expectedRevision=0,
            ),
        )


def test_undo_skipped_meal_restores_it_and_reports_the_new_repeat():
    from tests.unit.kitchen.test_engine import run

    state = variety_state()
    current = plan()
    current["meals"][0] = with_dish(current["meals"][0])
    state = run(state, "plan.save", {"plan": current})
    state = run(state, "plan.confirm", {"id": "plan"})
    state = run(
        state,
        "meal.status",
        {
            "planId": "plan",
            "mealId": current["meals"][0]["id"],
            "status": "skipped",
        },
    )
    skipped_audit = state["audit"][-1]["id"]
    state = run(
        state,
        "meal.save",
        {
            "planId": "plan",
            "meal": with_dish(state["plans"][0]["meals"][5]),
        },
    )
    state = run(state, "change.undo", {"auditId": skipped_audit})
    assert state["plans"][0]["meals"][0]["status"] == "planned"
    assert next(a for a in state["audit"] if a["id"] == skipped_audit)["undone"] is True
    assert any(v["kind"] == "repeat" for v in plan_rule_violations(state, state["plans"][0]))


@pytest.mark.parametrize("unused_recipes", [[], [recipe()]])
async def test_bootstrap_cannot_finish_with_only_existing_stock_or_unused_generated_recipes(
    unused_recipes,
):
    state = initial_state()
    state["inventory"] = [
        {
            "id": f"stock-{i}",
            "name": name,
            "type": "Protein",
            "portions": 100,
            "location": "Freezer",
            "prepared": True,
            "addedOn": "2026-09-19",
            "priority": False,
        }
        for i, name in enumerate(["Chicken meatballs", "Salmon patties"])
    ]
    candidate = plan()
    for index, meal in enumerate(candidate["meals"]):
        component = meal["components"][0]
        component.pop("recipeId")
        item = state["inventory"][(index // 3) % 2]
        component.update(inventoryId=item["id"], name=item["name"], type=item["type"])
    provider = SequenceProvider(compact_fixture({"recipes": unused_recipes, "plan": candidate}))
    repo = MemoryRepository(state)
    with pytest.raises(ValueError, match="Bootstrap requires"):
        await KitchenAI(repo, None, provider, compact_weekly=False).generate(
            "scope",
            GenerateRequest(
                weekStart="2026-09-21", expectedRevision=0, operationId="stock-only-bootstrap"
            ),
        )
    assert repo.state == state


@pytest.mark.parametrize("name", ["Rice / grilled chicken", "Chicken rice (Rice)"])
def test_mixed_dish_cannot_use_plain_staple_alias_to_bypass_repeat_rule(name):
    state = variety_state()
    state["recipes"][1].update(
        name=name,
        ingredients=[
            {"name": "Rice", "quantity": 100, "unit": "g"},
            {"name": "Chicken", "quantity": 200, "unit": "g"},
        ],
    )
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][5] = with_dish(candidate["meals"][5])
    with pytest.raises(ValueError, match="repeat"):
        validate_plan_timing(state, candidate)


def test_bilingual_plain_rice_name_remains_exempt():
    state = initial_state()
    state["recipes"] = [{**recipe(), "name": "米饭 (Rice)"}]
    validate_plan_timing(state, plan())


def test_distinct_mixed_dishes_do_not_conflict_merely_for_sharing_rice_alias():
    state = variety_state()
    state["recipes"][1]["name"] = "Rice / grilled chicken"
    state["recipes"].append(dish("fish", "Rice / grilled fish"))
    candidate = plan()
    candidate["meals"][0] = with_dish(candidate["meals"][0])
    candidate["meals"][5] = with_dish(candidate["meals"][5], "fish")
    validate_plan_timing(state, candidate)


def test_ai_generated_prep_requires_recipe_but_manual_prep_remains_flexible():
    from recipe_agent.domain.kitchen.ai import output_models
    from recipe_agent.domain.kitchen.contracts import PrepTask

    prep = {
        "id": "vegetables",
        "name": "Weekend Vegetable Prep",
        "type": "Vegetables",
        "plannedPortions": 9,
        "actualPortions": 0,
        "activeMinutes": 10,
        "elapsedMinutes": 10,
        "steps": ["Wash and chop vegetables"],
        "status": "planned",
        "liked": False,
        "inputs": [],
        "equipment": [],
        "dependencies": [],
    }
    PrepTask.model_validate(prep)
    output = bootstrap_result()
    output["plan"]["prep"] = [prep]
    Generation, _, _ = output_models()
    with pytest.raises(ValueError, match="recipeId"):
        Generation.model_validate(output)
    prep["recipeId"] = "dish-0"
    assert Generation.model_validate(output).plan.prep[0].recipeId == "dish-0"


def test_ai_fresh_meals_require_recipe_reference_and_prepared_stock_is_supported():
    from recipe_agent.domain.kitchen.ai import output_models

    output = bootstrap_result()
    component = output["plan"]["meals"][0]["components"][0]
    component.pop("recipeId")
    Generation, _, _ = output_models()
    with pytest.raises(ValueError, match="recipeId"):
        Generation.model_validate(output)
    component["inventoryId"] = "existing-prepared-stock"
    assert (
        Generation.model_validate(output).plan.meals[0].components[0].inventoryId
        == "existing-prepared-stock"
    )


def test_plain_steamed_rice_bilingual_name_is_recognized_as_staple():
    state = initial_state()
    state["recipes"] = [{**recipe(), "name": "米饭 (Plain Steamed Rice)"}]
    validate_plan_timing(state, plan())


async def test_generation_distributes_configured_daily_time_budget_before_provider_planning():
    state = initial_state()
    state["settings"]["maxDailyActiveMinutes"] = 45
    state["settings"]["maxPrepMinutes"] = 180
    provider = SequenceProvider(compact_fixture(bootstrap_result()))
    await KitchenAI(MemoryRepository(state), None, provider, compact_weekly=False).generate(
        "scope", GenerateRequest(weekStart="2026-09-21", expectedRevision=0, operationId="budget")
    )
    context = json.loads(provider.requests[0][1]["content"])
    assert context["planningBudget"]["totalDailyActiveMinutes"] == 45
    assert context["planningBudget"]["suggestedActiveMinutes"] == {
        "breakfast": 7.5,
        "lunch": 15,
        "dinner": 22.5,
    }
    assert context["planningBudget"]["maxPrepActiveMinutes"] == 180
    assert context["planningBudget"]["maxOrdinaryPrepElapsedMinutes"] == 180


def nothing_to_change():
    return SequenceProvider(
        {"reply": "Nothing to change", "meals": [], "needsClarification": False}
    )


async def test_chat_is_told_which_dishes_each_changing_meal_must_avoid():
    state = variety_state()
    current = plan()
    current["meals"][0] = with_dish(current["meals"][0])  # Monday breakfast
    state["plans"] = [current]
    tuesday = current["meals"][3]
    provider = nothing_to_change()
    await KitchenAI(MemoryRepository(state), None, provider).chat(
        "scope",
        ChatRequest(
            planId="plan", message="Change this", mealIds=[tuesday["id"]], expectedRevision=0
        ),
    )
    payload = json.loads(provider.requests[0][1]["content"])
    assert payload["avoidDishes"] == {
        tuesday["id"]: [
            {
                "dish": "Chicken meatballs",
                "usedOn": current["meals"][0]["day"],
                "recipeId": "chicken",
            }
        ]
    }


async def test_a_dish_named_like_a_saved_recipe_is_that_recipe():
    state = variety_state()
    current = plan()
    state["plans"] = [current]
    target = deepcopy(current["meals"][8])
    target["components"][0] = {
        "id": target["components"][0]["id"],
        "name": "Chicken meatballs",
        "type": "Protein",
        "portions": target["components"][0]["portions"],
    }
    provider = SequenceProvider(
        {"reply": "Chicken tonight", "meals": [target], "needsClarification": False}
    )
    result = await KitchenAI(MemoryRepository(state), None, provider).chat(
        "scope",
        ChatRequest(planId="plan", message="Chicken", mealIds=[target["id"]], expectedRevision=0),
    )
    assert result["meals"][0]["components"][0]["recipeId"] == "chicken"
    assert len(provider.requests) == 1


async def test_chat_may_add_a_complete_new_recipe_within_the_weekly_allowance():
    state = variety_state()
    current = plan()
    state["plans"] = [current]
    tofu = {**dish("tofu", "Mapo tofu"), "source": "AI-generated"}
    target = with_dish(current["meals"][8], "tofu", "Mapo tofu")
    answer = {"reply": "Tofu", "meals": [target], "needsClarification": False, "recipes": [tofu]}
    request = ChatRequest(planId="plan", message="Tofu", mealIds=[target["id"]], expectedRevision=0)
    result = await KitchenAI(MemoryRepository(state), None, SequenceProvider(answer)).chat(
        "scope", request
    )
    assert [r["id"] for r in result["recipes"]] == ["tofu"]
    assert result["meals"][0]["components"][0]["recipeId"] == "tofu"
    # The weekly target is advice; a user-requested new dish is still usable.
    state["settings"]["newRecipesPerWeek"] = 0
    refused = await KitchenAI(MemoryRepository(state), None, SequenceProvider(answer)).chat(
        "scope", request
    )
    assert refused["meals"][0]["components"][0]["recipeId"] == "tofu"


async def test_an_answer_to_a_whole_week_question_redoes_the_week_with_it():
    state = variety_state()
    current = plan()
    everything = sorted(m["id"] for m in current["meals"])
    current["chat"] = [
        {"id": "ask", "role": "user", "text": "Rebuild the whole week", "mealIds": []},
        {"id": "question", "role": "assistant", "text": "Which style?", "mealIds": everything},
    ]
    state["plans"] = [current]
    provider = nothing_to_change()
    result = await KitchenAI(MemoryRepository(state), None, provider).chat(
        "scope",
        ChatRequest(
            planId="plan",
            # Naming the weekend in the answer does not shrink the question's scope.
            message="工作日极简省事，周末可以稍微复杂一点",  # noqa: RUF001
            expectedRevision=0,
            answeringClarification=True,
        ),
    )
    # The week generator gets the request, Stu's question and the answer.
    prompt = json.loads(provider.requests[0][1]["content"])["prompt"]
    assert "Rebuild the whole week" in prompt and "Which style?" in prompt
    assert "周末可以稍微复杂一点" in prompt
    # This provider never drafts a week, so nothing is proposed and the reply says why.
    assert result["meals"] == [] and result["needsClarification"] is False
    assert result["scope"] == ",".join(everything)


async def test_a_redone_week_is_proposed_meal_by_meal_keeping_locked_meals():
    state = variety_state()
    state["settings"]["newRecipesPerWeek"] = 21
    current = plan()
    current["meals"][0]["locked"] = True
    locked = deepcopy(current["meals"][0])
    current["chat"] = [
        {"id": "ask", "role": "user", "text": "Rebuild the whole week", "mealIds": []},
        {
            "id": "question",
            "role": "assistant",
            "text": "Which style?",
            "mealIds": sorted(m["id"] for m in current["meals"]),
        },
    ]
    state["plans"] = [current]
    menu = compact_fixture(bootstrap_result())
    result = await KitchenAI(MemoryRepository(state), None, SequenceProvider(menu)).chat(
        "scope",
        ChatRequest(
            planId="plan", message="Simple", expectedRevision=0, answeringClarification=True
        ),
    )
    changed = {m["id"] for m in result["meals"]}
    assert locked["id"] not in changed and len(changed) == 20
    assert {r["id"] for r in result["recipes"]} and result["prep"] is not None


def test_a_stray_note_in_a_model_answer_is_dropped_not_fatal():
    from recipe_agent.domain.kitchen.ai import prune_extras
    from recipe_agent.domain.kitchen.compact_generation import CompactGeneration

    output = compact_fixture(bootstrap_result())
    output["recipes"][0]["/**"] = "宝宝份不额外加盐"
    output["mealTemplates"][0]["note"] = "extra"
    cleaned = prune_extras(CompactGeneration, output)
    assert "/**" not in cleaned["recipes"][0] and "note" not in cleaned["mealTemplates"][0]
    CompactGeneration.model_validate(cleaned)
    # Missing fields are not invented: validation still refuses them.
    del output["days"]
    with pytest.raises(ValueError):
        CompactGeneration.model_validate(prune_extras(CompactGeneration, output))


def test_weekdays_and_the_weekend_together_mean_the_whole_week():
    from recipe_agent.domain.kitchen.ai import resolve_meal_scope

    meals = plan()["meals"]
    assert resolve_meal_scope("工作日极简省事，周末可以稍微复杂一点", meals) == {  # noqa: RUF001
        m["id"] for m in meals
    }
    weekend = resolve_meal_scope("周末可以复杂一点", meals)
    assert {m["day"] for m in meals if m["id"] in weekend} == {"2026-09-26", "2026-09-27"}
