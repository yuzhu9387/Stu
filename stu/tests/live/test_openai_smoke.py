import os
from uuid import uuid4

import pytest

from recipe_agent.bootstrap import build_runtime
from recipe_agent.config import Settings
from recipe_agent.domain.conversation.react import AgentContext
from recipe_agent.domain.identity.locale import Locale


@pytest.mark.live
@pytest.mark.asyncio
async def test_configured_openai_model_returns_a_valid_react_decision() -> None:
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
    finally:
        await runtime.aclose()
