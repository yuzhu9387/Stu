"""Stu fills only the blanks of a meal's dishes; nothing is saved."""

import json
from copy import deepcopy

import pytest

from recipe_agent.domain.kitchen.ai import FillRequest, KitchenAI
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository
from tests.unit.kitchen.test_ai_variety import SequenceProvider

from .test_dish_baskets import household


def answer():
    return {
        "dishes": [
            {
                "id": "greens",
                "type": "Vegetables",
                "secondaryTypes": [],
                "ingredients": [
                    {"name": "菠菜", "quantity": 200, "unit": "g"},
                    {"name": "盐", "quantity": 0, "unit": "适量"},
                ],
                "steps": ["焯水", "蒜末炒香下菠菜"],
                "activeMinutes": 8,
                "elapsedMinutes": 5,
            },
            {
                "id": "egg",
                "type": "Carbs",
                "ingredients": [{"name": "鸡蛋", "quantity": 1, "unit": "个"}],
                "steps": ["Stu's steps"],
                "activeMinutes": 3,
                "elapsedMinutes": 10,
            },
            {
                "id": "stray",
                "type": "Other",
                "ingredients": [],
                "steps": [],
                "activeMinutes": 1,
                "elapsedMinutes": 1,
            },
        ]
    }


async def fill(request):
    state = household()
    state["settings"]["people"] = 1
    state["settings"]["allergies"] = ["花生"]
    state["settings"]["guidance"] = [
        {"id": "kid", "title": "以娃为主", "content": "忌辛辣", "enabled": True, "version": 1}
    ]
    repository = MemoryRepository(deepcopy(state))
    provider = SequenceProvider(answer())
    result = await KitchenAI(repository, None, provider).fill("household", request)
    return result, provider, repository, state


async def test_stu_fills_only_what_is_blank():
    request = FillRequest(
        slot="dinner",
        dishes=[
            {"id": "greens", "name": "蒜蓉菠菜", "portions": 1},
            {"id": "egg", "name": "蒸蛋", "type": "Protein", "steps": ["Mine"], "activeMinutes": 5},
        ],
    )
    result, provider, repository, state = await fill(request)
    greens, egg = result["dishes"]
    assert greens["ingredients"] == [{"name": "菠菜", "quantity": 200, "unit": "g"}]
    assert greens["steps"] == ["焯水", "蒜末炒香下菠菜"]
    # Elapsed time is never shorter than the hands-on time.
    assert (greens["activeMinutes"], greens["elapsedMinutes"]) == (8, 8)
    # What the household gave stays as given.
    assert (egg["type"], egg["steps"], egg["activeMinutes"]) == ("Protein", ["Mine"], 5)
    assert egg["ingredients"] == [{"name": "鸡蛋", "quantity": 1, "unit": "个"}]
    assert [d["id"] for d in result["dishes"]] == ["greens", "egg"]
    sent = json.loads(provider.requests[0][1]["content"])
    assert sent["settings"]["people"] == 1 and sent["settings"]["allergies"] == ["花生"]
    assert [g["title"] for g in sent["settings"]["guidance"]] == ["以娃为主"]
    assert repository.state == state


async def test_a_meal_with_no_dishes_is_refused():
    with pytest.raises(ValueError):
        FillRequest(slot="lunch", dishes=[])
