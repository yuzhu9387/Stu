"""The assistant (MCP) reaches everything the app can do: every engine
command except the confirmation snapshot, the shopping note, Changed meals,
+ Prep from the fridge, and Stu's previews (fill, compose, link import) and
partial apply."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

from recipe_agent.api.v1.kitchen_mcp import COMMANDS, dispatch, tool_definitions
from recipe_agent.domain.kitchen import ai as kitchen_ai
from recipe_agent.domain.kitchen.ai import KitchenAI
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository
from tests.unit.kitchen.test_ai_variety import SequenceProvider

from .test_dish_baskets import household, recipe
from .test_prep_from_fridge import fridge_prep

ENGINE = Path(__file__).parents[3] / "src/recipe_agent/domain/kitchen/engine.py"


def engine_commands() -> set[str]:
    source = ENGINE.read_text()
    kinds = set(re.findall(r'kind == "([a-z]+\.[a-zA-Z]+)"', source))
    for group in re.findall(r"kind in \{([^}]*)\}", source):
        kinds |= set(re.findall(r'"([a-z]+\.[a-zA-Z]+)"', group))
    categories = {"meal": ["save", "delete", "leftovers", "status", "like", "lock", "include"]}
    categories["prep"] = ["save", "delete", "status", "like"]
    kinds |= {f"{c}.{a}" for c, actions in categories.items() for a in actions}
    return kinds


async def call(ai, name, arguments, rpc_id=1):
    message = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    result = (await dispatch(message, ai, "scope", getattr(ai, "background", None)))["result"]
    assert not result["isError"], result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


async def command(ai, repo, kind, payload):
    return await call(
        ai,
        "kitchen_command",
        {
            "type": kind,
            "payload": payload,
            "expectedRevision": repo.state["revision"],
            "operationId": f"{kind}:{repo.state['revision']}",
        },
    )


def test_every_engine_command_reaches_the_assistant_but_the_confirmation_snapshot():
    kinds = engine_commands()
    assert {"shopping.save", "shopping.delete", "shopping.putAway", "meal.status"} <= kinds
    assert kinds - {"plan.fulfill"} <= set(COMMANDS)
    assert "plan.fulfill" not in COMMANDS


def test_the_new_previews_and_partial_apply_are_tools():
    tools = {tool["name"]: tool for tool in tool_definitions()}
    assert {"kitchen_fill", "kitchen_compose", "kitchen_import_link"} <= set(tools)
    assert "mealIds" in tools["kitchen_task_apply"]["inputSchema"]["properties"]
    described = tools["kitchen_command"]["description"]
    for shape in ("shopping.putAway", "meal.status", "prep.status"):
        assert f"{shape}:" in described


async def test_the_shopping_note_changed_meals_and_fridge_prep_through_the_assistant():
    repo = MemoryRepository(household())
    ai = SimpleNamespace(repository=repo)
    await command(
        ai,
        repo,
        "shopping.save",
        {"item": {"id": "milk", "name": "牛奶", "quantity": 2, "checked": True}},
    )
    assert (await call(ai, "kitchen_read", {}))["shoppingList"][0]["name"] == "牛奶"
    await command(ai, repo, "shopping.putAway", {"items": [{"id": "milk", "location": "fridge"}]})
    assert repo.state["shoppingList"] == []
    assert any(i["name"] == "牛奶" and i["portions"] == 2 for i in repo.state["inventory"])
    await command(
        ai, repo, "shopping.save", {"item": {"id": "eggs", "name": "鸡蛋", "checked": False}}
    )
    await command(ai, repo, "shopping.delete", {"id": "eggs"})
    assert repo.state["shoppingList"] == []

    await command(ai, repo, "prep.save", {"planId": "plan", "prep": fridge_prep()})
    await command(
        ai,
        repo,
        "prep.status",
        {
            "planId": "plan",
            "prepId": "egg-pancakes",
            "status": "completed",
            "actualPortions": 2,
            "location": "fridge",
        },
    )
    box = next(i for i in repo.state["inventory"] if i["id"] == "prep-egg-pancakes")
    assert (box["portions"], box["location"]) == (2, "fridge")

    await command(ai, repo, "plan.confirm", {"id": "plan"})
    await command(
        ai,
        repo,
        "meal.status",
        {"planId": "plan", "mealId": "lunch", "status": "changed", "note": "外卖"},
    )
    meal = repo.state["plans"][0]["meals"][0]
    assert (meal["status"], meal["note"]) == ("changed", "外卖")


async def test_stus_previews_through_the_assistant_save_nothing(monkeypatch):
    state = household()
    repo = MemoryRepository(state)
    filled = {
        "dishes": [
            {
                "id": "g",
                "type": "Vegetables",
                "ingredients": [{"name": "西兰花", "quantity": 200, "unit": "g"}],
                "steps": ["焯水"],
                "activeMinutes": 5,
                "elapsedMinutes": 8,
            }
        ]
    }
    ai = KitchenAI(repo, None, SequenceProvider(filled))
    result = await call(
        ai,
        "kitchen_fill",
        {"slot": "dinner", "dishes": [{"id": "g", "name": "西兰花", "portions": 1}]},
    )
    assert result["dishes"][0]["steps"] == ["焯水"]

    dish = {"recipe": recipe(id="model-id"), "uses": [{"inventoryId": "eggs", "portions": 2}]}
    ai = KitchenAI(repo, None, SequenceProvider(dish))
    composed = await call(ai, "kitchen_compose", {"inventoryIds": ["eggs"]})
    assert composed["uses"] == [{"inventoryId": "eggs", "portions": 2}]

    async def fetched(url):
        return "Title: 番茄炒蛋\nIngredients: 鸡蛋 3个"

    monkeypatch.setattr(kitchen_ai, "fetch_page_text", fetched)
    candidate = {
        "id": "d",
        "liked": False,
        "source": "p",
        "name": "番茄炒蛋",
        "type": "Protein",
        "mealTypes": ["dinner"],
        "tags": [],
        "servings": 2,
        "activeMinutes": 10,
        "elapsedMinutes": 10,
        "ingredients": [{"name": "鸡蛋", "quantity": 3, "unit": "个"}],
        "steps": ["炒"],
        "incomplete": True,
    }
    ai = KitchenAI(repo, None, SequenceProvider({"recipes": [candidate]}))
    imported = await call(ai, "kitchen_import_link", {"url": "https://recipes.example/eggs"})
    assert imported["recipes"][0]["source"] == "https://recipes.example/eggs"
    assert repo.state == state


async def test_only_the_chosen_meals_of_an_answer_are_applied_through_the_assistant():
    applied = []

    class Background:
        async def apply(self, scope, task_id, meal_ids=None):
            applied.append(meal_ids)
            return {"applied": True}

    ai = SimpleNamespace(repository=MemoryRepository(household()), background=Background())
    task = "5b0f6f8e-6d8a-4f5e-9e4a-2f1f0a1b2c3d"
    await call(ai, "kitchen_task_apply", {"taskId": task, "mealIds": ["lunch"]})
    await call(ai, "kitchen_task_apply", {"taskId": task})
    assert applied == [["lunch"], None]
