from collections.abc import Iterable
from uuid import uuid4

import pytest

from recipe_agent.config import Settings
from recipe_agent.domain.conversation.react import (
    AgentContext,
    ReadOnlyToolDefinition,
)
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.ai.react_model import (
    LiteLLMReactModel,
    ReactModelResponseError,
)


def context() -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        account_id=uuid4(),
        household_id=uuid4(),
        locale=Locale.EN_US,
        message="Find dinner",
    )


def definitions() -> tuple[ReadOnlyToolDefinition, ...]:
    return (
        ReadOnlyToolDefinition(
            name="search_family_recipes",
            description="Search family-visible recipes.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    )


def completion(content: str, *, total_tokens: int = 0) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": max(0, total_tokens - 2),
            "completion_tokens": min(2, total_tokens),
            "total_tokens": total_tokens,
        },
    }


class RecordedACompletion:
    def __init__(self, responses: Iterable[object]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_adapter_passes_bounded_provider_options_and_read_only_tools() -> None:
    fake = RecordedACompletion(
        [
            completion(
                '{"tool_call":{"name":"search_family_recipes","arguments":{}},"final":null}',
                total_tokens=11,
            )
        ]
    )
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=30.0,
        max_retries=2,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    decision = await model.decide(context(), ())

    assert decision.tool_call is not None
    call = fake.calls[0]
    assert call["model"] == "openai/gpt-5.1"
    assert call["reasoning_effort"] == "high"
    assert call["timeout"] == 30.0
    assert call["max_retries"] == 2
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_family_recipes",
                "description": "Search family-visible recipes.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    assert call["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert model.usage_records[0].total_tokens == 11


@pytest.mark.asyncio
async def test_invalid_decision_gets_exactly_one_structured_output_repair() -> None:
    fake = RecordedACompletion(
        [
            completion("{}"),
            completion(
                '{"tool_call":null,"final":{"thinking":"Summary","plan":"Plan",'
                '"act":"No tools used","answer":"Answer","suggested_actions":[]}}'
            ),
        ]
    )
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=20,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    decision = await model.decide(context(), ())

    assert decision.final is not None
    assert len(fake.calls) == 2
    assert fake.calls[1]["messages"][-2] == {"role": "assistant", "content": "{}"}  # type: ignore[index]
    assert "Repair" in fake.calls[1]["messages"][-1]["content"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_invalid_repair_is_not_retried_indefinitely() -> None:
    fake = RecordedACompletion([completion("{}"), completion("{}")])
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=20,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    with pytest.raises(ReactModelResponseError, match="one repair"):
        await model.decide(context(), ())

    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_provider_failure_switches_to_fallback_once() -> None:
    fake = RecordedACompletion(
        [
            TimeoutError("primary timed out"),
            completion(
                '{"tool_call":null,"final":{"thinking":"Summary","plan":"Plan",'
                '"act":"No tools used","answer":"Answer","suggested_actions":[]}}'
            ),
        ]
    )
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=20,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    decision = await model.decide(context(), ())

    assert decision.final is not None
    assert [call["model"] for call in fake.calls] == [
        "openai/gpt-5.1",
        "openai/gpt-5-mini",
    ]


@pytest.mark.asyncio
async def test_both_provider_models_fail_without_repeating_transition() -> None:
    fake = RecordedACompletion([TimeoutError("primary"), TimeoutError("fallback")])
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=20,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    with pytest.raises(TimeoutError, match="fallback"):
        await model.decide(context(), ())

    assert [call["model"] for call in fake.calls] == [
        "openai/gpt-5.1",
        "openai/gpt-5-mini",
    ]


def test_react_settings_have_validated_exact_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.litellm_chat_model == "openai/gpt-5.1"
    assert settings.litellm_fallback_model == "openai/gpt-5-mini"
    assert settings.litellm_reasoning_effort == "high"
    assert settings.litellm_timeout_seconds == 30.0
    assert settings.litellm_max_retries == 2
    assert settings.react_max_iterations == 5

    with pytest.raises(ValueError):
        Settings(_env_file=None, litellm_timeout_seconds=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, litellm_max_retries=20)
    with pytest.raises(ValueError):
        Settings(_env_file=None, react_max_iterations=6)
