"""Ask Stu from the fridge: an answer from what is in the fridge and the
household's quick and liked recipes, following its guidance and the child's
age. It only answers; nothing in the kitchen changes."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from recipe_agent.domain.kitchen.ai import AskRequest, KitchenAI
from recipe_agent.domain.kitchen.engine import parse
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository
from tests.unit.kitchen.test_ai_variety import SequenceProvider

from .test_dish_baskets import household, recipe


def kitchen():
    state = household(
        recipes=[
            recipe(tags=["Quick"]),
            recipe(id="r-slow", name="红烧肉", tags=["Weekend"]),
            recipe(id="r-liked", name="蒸蛋", liked=True),
            recipe(id="r-fast", name="番茄面", tags=["快手"]),
        ]
    )
    state["settings"]["guidance"] = [
        {"id": "kid", "title": "以娃为主", "content": "忌辛辣", "enabled": True, "version": 1},
        {"id": "off", "title": "Off", "content": "ignored", "enabled": False, "version": 1},
    ]
    state["settings"]["childAge"] = 20
    state["inventory"][1]["portions"] = 0  # the spinach is used up
    return state


async def ask(state, message="今晚吃什么", answer=None):
    repository = MemoryRepository(deepcopy(state))
    provider = SequenceProvider(answer or {"reply": "  今晚做菠菜鸡蛋饼吧。 "})
    result = await KitchenAI(repository, None, provider).ask(
        "household", AskRequest(message=message)
    )
    return result, provider, repository


async def test_stu_answers_from_the_fridge_and_quick_recipes_and_changes_nothing():
    state = kitchen()
    result, provider, repository = await ask(state)
    assert result == {"reply": "今晚做菠菜鸡蛋饼吧。"}
    sent = json.loads(provider.requests[0][1]["content"])
    assert sent["question"] == "今晚吃什么"
    assert [food["name"] for food in sent["fridge"]] == ["鸡蛋"]
    assert sorted(r["name"] for r in sent["recipes"]) == ["番茄面", "菠菜鸡蛋饼", "蒸蛋"]
    assert [g["title"] for g in sent["settings"]["guidance"]] == ["以娃为主"]
    assert sent["settings"]["childAge"] == 20
    assert "read-only" in provider.requests[0][0]["content"]
    assert repository.state == state


async def test_a_question_is_needed_and_kept_short():
    with pytest.raises(ValidationError):
        AskRequest(message="   ")
    with pytest.raises(ValidationError):
        AskRequest(message="x" * 1001)


async def test_an_empty_answer_is_an_error():
    with pytest.raises(ValueError):
        await ask(kitchen(), answer={"reply": "  "})


def test_the_reply_shape_is_plain_text():
    from recipe_agent.domain.kitchen.ai import AskReply

    assert parse(AskReply, {"reply": "好"}) == {"reply": "好"}
    with pytest.raises(ValidationError):
        parse(AskReply, {"reply": "好", "changes": []})
