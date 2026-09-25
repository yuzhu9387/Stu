from datetime import date

from recipe_agent.domain.kitchen.ai import planning_preferences
from recipe_agent.domain.kitchen.engine import initial_state
from tests.unit.kitchen.test_ai_scheduling_mcp import plan, recipe


def test_preferences_combine_likes_stock_and_previous_week_without_duplicate_versions():
    state = initial_state()
    state["recipes"] = [
        {"id": "liked", "liked": True},
        {"id": "stock", "liked": False},
        {"id": "recent", "liked": False},
    ]
    state["inventory"] = [
        {
            "id": "new",
            "recipeId": "stock",
            "name": "Stock",
            "portions": 3,
            "priority": False,
            "addedOn": "2026-09-16",
        },
        {
            "id": "old",
            "recipeId": "stock",
            "name": "Stock",
            "portions": 3,
            "priority": True,
            "addedOn": "2026-09-10",
        },
        {
            "id": "empty",
            "recipeId": "recent",
            "name": "Recent",
            "portions": 0,
            "priority": True,
            "addedOn": "2026-09-01",
        },
    ]
    meal = {
        "id": "dinner",
        "day": "2026-09-14",
        "slot": "dinner",
        "liked": True,
        "status": "completed",
        "components": [{"recipeId": "recent"}, {"recipeId": "liked"}],
    }
    previous = {
        "id": "old",
        "weekStart": "2026-09-14",
        "status": "confirmed",
        "version": 2,
        "meals": [meal],
        "prep": [{"id": "prep", "recipeId": "liked", "liked": True}],
    }
    state["plans"] = [
        previous,
        {**previous, "id": "old-draft", "status": "draft", "version": 3},
        {**previous, "id": "older", "weekStart": "2026-09-07", "meals": []},
    ]
    result = planning_preferences(state, date(2026, 9, 21))
    ranked = {item["recipeId"]: item for item in result["rankedRecipes"]}
    assert ranked["liked"]["recipeLiked"] is True
    assert ranked["liked"]["likedMealCount"] == 0
    assert result["likedCombinations"] == [{"recipeIds": ["liked", "recent"], "count": 1}]
    assert ranked["liked"]["likedPrepCount"] == 2
    assert ranked["liked"]["preferenceScore"] > ranked["recent"]["preferenceScore"]
    assert [i["inventoryId"] for i in result["inventoryUseOrder"]] == ["old", "new"]
    assert result["previousWeek"]["weekStart"] == "2026-09-14"
    assert len(result["previousWeek"]["completedMeals"]) == 1
    assert result["previousWeek"]["recipeCounts"] == {"liked": 1, "recent": 1}
    assert result["policy"]["avoidRepeatingPreviousWeek"] is True


def test_empty_preferences_are_explicit_and_bounded():
    result = planning_preferences(initial_state(), date(2026, 9, 21))
    assert result["rankedRecipes"] == []
    assert result["inventoryUseOrder"] == []
    assert result["previousWeek"]["completedMeals"] == []


async def test_generate_sends_ranked_preferences_and_separate_completed_history():
    import json

    import pytest

    from recipe_agent.domain.kitchen.ai import GenerateRequest, KitchenAI

    state = initial_state()
    state["recipes"] = [
        {**recipe(), "id": "ordinary", "liked": False},
        {
            **recipe(),
            "id": "favorite",
            "liked": True,
            "source": "data:image/png;base64," + "A" * 10000,
        },
    ]

    class Repository:
        async def get(self, scope):
            return state

    class CaptureProvider:
        async def complete(self, messages, schema, *, vision=False):
            self.messages = messages
            raise RuntimeError("request captured")

    provider = CaptureProvider()
    with pytest.raises(RuntimeError, match="request captured"):
        await KitchenAI(Repository(), None, provider, compact_weekly=False).generate(
            "household",
            GenerateRequest(
                weekStart="2026-09-21", expectedRevision=0, operationId="preference-test"
            ),
        )
    request = json.loads(provider.messages[1]["content"])
    assert request["workspace"]["recipes"][0]["id"] == "favorite"
    assert "data:image" not in provider.messages[1]["content"]
    assert "A" * 100 not in provider.messages[1]["content"]
    assert state["recipes"][1]["source"].startswith("data:image/png;base64,")
    assert "plans" not in request["workspace"]
    assert request["planningPreferences"]["previousWeek"]["weekStart"] == "2026-09-14"
    assert request["planningPreferences"]["previousWeek"]["completedMeals"] == []
    assert "serving and cleanup" in provider.messages[0]["content"]
    assert (
        "Passive fermentation or baking waiting is not active work"
        in provider.messages[0]["content"]
    )


def test_planning_source_sanitization_preserves_saved_source():
    from recipe_agent.domain.kitchen.ai import planning_recipe

    original = {"id": "image", "source": "data:image/png;base64," + "A" * 10000}
    bounded = planning_recipe(original)
    assert bounded["source"] == "Imported image (saved with recipe)"
    assert original["source"].startswith("data:image/png;base64,")
    assert len(planning_recipe({"source": "text " * 1000})["source"]) == 2000


async def test_chat_context_does_not_include_original_image_data():
    import pytest

    from recipe_agent.domain.kitchen.ai import ChatRequest, KitchenAI

    state = initial_state()
    source = "data:image/png;base64," + "A" * 10000
    state["recipes"] = [{**recipe(), "id": "image", "source": source}]
    state["plans"] = [
        {
            **plan(),
            "id": "plan",
            "meals": [{"id": "meal", "locked": False, "status": "planned", "components": []}],
        }
    ]

    class Repository:
        async def get(self, scope):
            return state

    class Provider:
        async def complete(self, messages, schema, *, vision=False):
            assert "data:image" not in messages[1]["content"]
            assert "A" * 100 not in messages[1]["content"]
            raise RuntimeError("safe context captured")

    with pytest.raises(RuntimeError, match="safe context captured"):
        await KitchenAI(Repository(), None, Provider(), compact_weekly=False).chat(
            "household",
            ChatRequest(
                planId="plan", message="Change this meal", mealIds=["meal"], expectedRevision=0
            ),
        )
    assert state["recipes"][0]["source"] == source


async def test_weekly_note_splits_into_new_preferences_without_saving_or_duplicating():
    from recipe_agent.domain.kitchen.ai import KitchenAI, PreferencesRequest
    from tests.unit.kitchen.test_ai_scheduling_mcp import FakeProvider, MemoryRepository

    state = initial_state()
    state["settings"]["guidance"] = [
        {
            "id": "baby",
            "title": "Baby portions",
            "content": "Small pieces.",
            "enabled": True,
            "version": 1,
        }
    ]
    repo = MemoryRepository(state)
    provider = FakeProvider(
        {
            "preferences": [
                {"title": "Use frozen meatballs", "content": "Finish the frozen meatballs first."},
                {"title": "  baby   PORTIONS ", "content": "Already a goal."},
                {"title": "Use frozen meatballs", "content": "Said twice in the note."},
            ]
        }
    )
    result = await KitchenAI(repo, None, provider, compact_weekly=False).preferences(
        "scope", PreferencesRequest(text="下周把冷冻的鸡肉丸用掉 宝宝份量小一点")
    )

    assert result == {
        "preferences": [
            {"title": "Use frozen meatballs", "content": "Finish the frozen meatballs first."}
        ]
    }
    messages, _, vision = provider.requests[0]
    assert not vision
    assert "下周把冷冻的鸡肉丸用掉" in messages[1]["content"]
    assert "Baby portions" in messages[1]["content"]
    assert repo.state["revision"] == 0
