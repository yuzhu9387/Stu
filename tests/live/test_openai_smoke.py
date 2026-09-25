import os
from uuid import uuid4

import pytest

from recipe_agent.bootstrap import build_runtime
from recipe_agent.config import Settings
from recipe_agent.domain.conversation.react import AgentContext
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.ai import ExtractRequest, KitchenAI, KitchenProvider
from recipe_agent.domain.kitchen.contracts import Recipe
from recipe_agent.domain.kitchen.repository import KitchenRepository


@pytest.mark.live
@pytest.mark.asyncio
async def test_configured_openai_model_and_kitchen_extraction() -> None:
    if os.getenv("RUN_LIVE_AI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_AI_TESTS=1 to call the configured provider")
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured")
    runtime = build_runtime(settings)
    try:
        decision = await runtime.agent_model.decide(
            AgentContext(
                run_id=uuid4(),
                account_id=uuid4(),
                household_id=uuid4(),
                locale=Locale.EN_US,
                message="Say which read-only tool you would use to list my saved recipes.",
            ),
            (),
        )
        assert (decision.tool_call is None) != (decision.final is None)
        # Synthetic input only; extraction previews do not write to the household database.
        text = (
            "菜名：燕麦粥。份量：2份。类别：碳水。适合早餐。"
            "食材：燕麦60克、水300毫升。主动操作时间：5分钟。总耗时：10分钟。"
            "步骤：1. 将燕麦和水倒入锅中。2. 加热并搅拌5分钟。"
            "3. 关火静置5分钟后分成2份。"
        )
        kitchen = KitchenAI(
            KitchenRepository(runtime.session_factory), settings, KitchenProvider(settings)
        )
        preview = await kitchen.extract(HouseholdScope(uuid4(), uuid4()), ExtractRequest(text=text))
        assert len(preview["recipes"]) == 1
        recipe = Recipe.model_validate(preview["recipes"][0])
        assert recipe.name == "燕麦粥"
        assert recipe.servings == 2
        assert recipe.activeMinutes == 5
        assert recipe.elapsedMinutes == 10
        assert recipe.ingredients and recipe.steps
        assert all(item.quantity > 0 and item.unit for item in recipe.ingredients)
        assert recipe.source == text
        assert not recipe.incomplete
    finally:
        await runtime.aclose()
