"""Stu keeps the household's rules and earlier requests on every adjustment, and
builds a week from ready-made food first."""

import json

from recipe_agent.domain.kitchen.ai import (
    ChatRequest,
    GenerateRequest,
    KitchenAI,
    prepared_stock,
)
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository, plan
from tests.unit.kitchen.test_ai_variety import SequenceProvider, variety_state


def household():
    state = variety_state()
    state["settings"]["guidance"] = [
        {
            "id": "ratio",
            "title": "午餐 1:1:1",
            "content": "蛋白质:蔬菜:碳水 = 1:1:1",
            "enabled": True,
            "version": 1,
        },
        {
            "id": "off",
            "title": "Old rule",
            "content": "no longer used",
            "enabled": False,
            "version": 1,
        },
    ]
    state["mealStylePresets"] = [
        {"key": "fridge_first", "label": "Use fridge items first", "enabled": True}
    ]
    state["inventory"] = [
        {
            "id": "buns",
            "name": "包子",
            "type": "Carbs",
            "portions": 6,
            "location": "freezer",
            "prepared": True,
            "addedOn": "2026-09-27",
            "priority": False,
        },
        {
            "id": "used-up",
            "name": "饺子",
            "type": "Carbs",
            "portions": 0,
            "location": "freezer",
            "prepared": True,
            "addedOn": "2026-09-27",
            "priority": False,
        },
        {
            "id": "eggs",
            "name": "鸡蛋",
            "type": "Protein",
            "portions": 50,
            "location": "fridge",
            "prepared": False,
            "addedOn": "2026-09-27",
            "priority": False,
        },
    ]
    current = plan()
    current["presets"] = ["fridge_first"]
    current["chat"] = [
        {
            "id": "u1",
            "role": "user",
            "text": "早上不要馒头",
            "mealIds": [],
        },
        {
            "id": "a1",
            "role": "assistant",
            "text": "好的",
            "mealIds": [],
        },
    ]
    state["plans"] = [current]
    return state


def test_prepared_stock_lists_ready_made_food_still_on_hand():
    assert [item["inventoryId"] for item in prepared_stock(household())] == ["buns"]


async def test_an_adjustment_carries_every_rule_and_earlier_request():
    state = household()
    provider = SequenceProvider({"reply": "OK", "meals": [], "needsClarification": False})
    await KitchenAI(MemoryRepository(state), None, provider).propose(
        state, ChatRequest(planId="plan", message="中午只吃包子", expectedRevision=0)
    )
    system = "\n".join(m["content"] for m in provider.requests[0] if m["role"] == "system")
    payload = json.loads(next(m["content"] for m in provider.requests[0] if m["role"] == "user"))
    assert "standing constraints" in system
    assert payload["standing"]["guidance"] == [
        {"title": "午餐 1:1:1", "content": "蛋白质:蔬菜:碳水 = 1:1:1"}
    ]
    assert payload["standing"]["presets"] == ["Use fridge items first"]
    assert payload["standing"]["earlierRequests"] == ["早上不要馒头"]
    assert [item["inventoryId"] for item in payload["preparedStock"]] == ["buns"]


async def test_a_week_is_built_from_prepared_food_first():
    state = household()
    provider = SequenceProvider({"recipes": [], "plan": state["plans"][0]})
    await KitchenAI(MemoryRepository(state), None, provider, compact_weekly=False).generate(
        "scope",
        GenerateRequest(
            weekStart=state["plans"][0]["weekStart"], expectedRevision=0, operationId="w"
        ),
    )
    system = provider.requests[0][0]["content"]
    payload = json.loads(provider.requests[0][1]["content"])
    assert "First place preparedStock" in system
    assert [item["inventoryId"] for item in payload["preparedStock"]] == ["buns"]
