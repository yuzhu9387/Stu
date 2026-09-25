"""Opt-in paid-provider acceptance using only an isolated synthetic household."""

import json
import os
from datetime import date
from itertools import pairwise
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pytest

from recipe_agent.config import Settings
from recipe_agent.domain.identity.service import HouseholdScope, IdentityService
from recipe_agent.domain.kitchen.ai import (
    ChatRequest,
    GenerateRequest,
    KitchenAI,
    KitchenProvider,
    complete_recipe,
)
from recipe_agent.domain.kitchen.repository import KitchenRepository
from recipe_agent.domain.kitchen.scheduling import validate_plan_timing


@pytest.mark.live
async def test_empty_library_generates_persisted_week_and_scoped_chat(session_factory):
    if os.getenv("RUN_LIVE_AI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_AI_TESTS=1 to call the configured provider")
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured")
    identity = IdentityService(session_factory=session_factory)
    account = await identity.consume_magic_link(
        (await identity.request_magic_link(f"ai-acceptance-{uuid4().hex}@example.test")).token
    )
    scope = HouseholdScope(account.account.id, account.household.id)
    repository = KitchenRepository(session_factory)
    initial = await repository.get(scope)
    assert not initial["recipes"] and not initial["plans"]

    async def command(kind, payload):
        state = await repository.get(scope)
        return await repository.command(
            scope,
            {
                "type": kind,
                "payload": payload,
                "expectedRevision": state["revision"],
                "operationId": uuid4().hex,
            },
        )

    await command("settings.save", {"settings": {**initial["settings"], "childAge": 36}})
    await command(
        "knowledge.save",
        {
            "document": {
                "id": "acceptance-reference",
                "title": "家庭膳食规划参考 (测试)",
                "category": "Meal planning",
                "content": "Use different main dishes on neighboring days. Include vegetables "
                "in lunch and dinner. Favor practical batch preparation. This is a synthetic "
                "household preference document, not medical advice.",
                "enabled": True,
            }
        },
    )
    await command(
        "knowledge.save",
        {
            "document": {
                "id": "disabled-reference",
                "title": "Disabled old preference",
                "category": "Meal planning",
                "content": "This retired document must not enter AI context.",
                "enabled": False,
            }
        },
    )
    provider = KitchenProvider(settings)
    calls = []

    class ObservedProvider:
        async def complete(self, messages, schema, *, vision=False):
            calls.append(messages)
            started = monotonic()
            print(f"Live provider request {len(calls)}: {schema.get('title')}", flush=True)
            if len(messages) > 2:
                print(messages[-1]["content"][:1500], flush=True)
            result = await provider.complete(messages, schema, vision=vision)
            print(f"Live provider returned in {monotonic() - started:.1f}s", flush=True)
            if artifact := os.getenv("KITCHEN_LIVE_ARTIFACT"):
                Path(artifact).with_suffix(f".attempt-{len(calls)}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            return result

    ai = KitchenAI(repository, settings, ObservedProvider())
    request = GenerateRequest(
        weekStart="2026-09-21",
        prompt="Plan for 2 adults and one 36-month-old child. Generate complete recipes because "
        "the library is empty. Keep breakfasts simple, with protein, vegetables and carbs "
        "across lunch and dinner. No consecutive-day repeat of dishes; Monday to Wednesday "
        "is allowed. Include practical weekend batch prep. Keep all three meals together "
        "within 30 hands-on minutes each day and ordinary weekend prep within 240 minutes. "
        "Use Chinese recipe names; English instructions are fine.",
        expectedRevision=(await repository.get(scope))["revision"],
        operationId=uuid4().hex,
    )
    result = await ai.generate(scope, request)
    state = await KitchenRepository(session_factory).get(scope)
    assert state == result["state"]
    assert len(state["plans"]) == 1
    plan = state["plans"][0]
    assert plan["status"] == "draft" and len(plan["meals"]) == 21
    assert len(state["recipes"]) > initial["settings"]["newRecipesPerWeek"]
    for recipe in state["recipes"]:
        complete_recipe(recipe, [])
    validate_plan_timing(state, plan)
    assert plan["prep"], "Requested weekend prep must be present"
    assert [doc["id"] for doc in plan["knowledgeSnapshot"]] == ["acceptance-reference"]
    assert plan["knowledgeSnapshot"][0]["version"] == 1
    context = json.loads(calls[0][1]["content"])
    assert [doc["id"] for doc in context["workspace"]["knowledgeDocuments"]] == [
        "acceptance-reference"
    ]
    # Check actual generated main-dish identities independently from the validator.
    recipes = {recipe["id"]: recipe for recipe in state["recipes"]}
    days = {}
    for meal in plan["meals"]:
        for component in meal["components"]:
            if component["type"] in {"Protein", "Vegetables"}:
                recipe = recipes[component["recipeId"]]
                days.setdefault(recipe["name"].casefold(), set()).add(
                    date.fromisoformat(meal["day"])
                )
    for name, used in days.items():
        ordered = sorted(used)
        assert all((b - a).days >= 2 for a, b in pairwise(ordered)), name
    before_retry = len(calls)
    assert (await ai.generate(scope, request))["state"] == state
    assert len(calls) == before_retry

    selected = plan["meals"][0]
    proposal = await ai.chat(
        scope,
        ChatRequest(
            planId=plan["id"],
            mealIds=[selected["id"]],
            message="Keep the same dish, portions and timing. Rewrite the preparation steps "
            "for this selected meal into concise English, including serving and cleanup.",
            expectedRevision=state["revision"],
        ),
    )
    assert not proposal["needsClarification"]
    assert [meal["id"] for meal in proposal["meals"]] == [selected["id"]]
    after = await repository.get(scope)
    assert after["plans"][0]["meals"] == plan["meals"], "Chat is a preview until applied"
    chat_context = json.loads(calls[-1][1]["content"])
    assert [doc["id"] for doc in chat_context["knowledgeDocuments"]] == ["acceptance-reference"]
    if artifact := os.getenv("KITCHEN_LIVE_ARTIFACT"):
        Path(artifact).write_text(
            json.dumps({"providerCalls": len(calls), "state": after}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
