import json
import os
from collections.abc import Iterable
from uuid import uuid4

import pytest

# Keep LiteLLM's import deterministic: no dotenv loading or remote cost-map lookup.
os.environ["LITELLM_MODE"] = "TEST"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

from litellm import ModelResponse

from recipe_agent.config import Settings
from recipe_agent.domain.conversation.react import (
    AgentContext,
    ReadOnlyToolDefinition,
)
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.ai.react_model import (
    LiteLLMReactModel,
    ReactModelProviderError,
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
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
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


def model_response(
    *,
    content: str | None,
    tool_calls: list[dict[str, object]] | None = None,
    total_tokens: int = 0,
) -> ModelResponse:
    return ModelResponse(
        model="openai/gpt-5.1",
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        usage={
            "prompt_tokens": max(0, total_tokens - 2),
            "completion_tokens": min(2, total_tokens),
            "total_tokens": total_tokens,
        },
    )


def native_tool_call(
    name: str = "search_family_recipes",
    arguments: str = "{}",
    *,
    call_id: str = "call_read_1",
) -> dict[str, object]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def final_json() -> str:
    return json.dumps(
        {
            "thinking": "Summary",
            "plan": "Plan",
            "act": "No tools used",
            "answer": "Answer",
            "suggested_actions": [],
        }
    )


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
            model_response(
                content=None,
                tool_calls=[native_tool_call()],
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
    assert call["tool_choice"] == "auto"
    assert call["parallel_tool_calls"] is False
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_family_recipes",
                "description": "Search family-visible recipes.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    ]
    assert call["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert call["response_format"]["json_schema"]["schema"] == (  # type: ignore[index]
        FinalAgentResponse.model_json_schema()
    )
    assert model.usage_records[0].total_tokens == 11


@pytest.mark.asyncio
async def test_adapter_parses_real_litellm_final_message_content() -> None:
    fake = RecordedACompletion([model_response(content=final_json(), total_tokens=7)])
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=30,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    decision = await model.decide(context(), ())

    assert decision.final is not None
    assert decision.final.answer == "Answer"
    assert model.usage_records[0].total_tokens == 7


@pytest.mark.asyncio
async def test_adapter_rejects_multiple_native_tool_calls() -> None:
    fake = RecordedACompletion(
        [
            model_response(
                content=None,
                tool_calls=[native_tool_call(), native_tool_call(call_id="call_read_2")],
            )
        ]
    )
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=30,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    with pytest.raises(ReactModelResponseError, match="exactly one"):
        await model.decide(context(), ())

    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_invalid_decision_gets_exactly_one_structured_output_repair() -> None:
    fake = RecordedACompletion(
        [
            completion("{}"),
            model_response(content=final_json()),
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
    assert [call["model"] for call in fake.calls] == ["openai/gpt-5.1", "openai/gpt-5.1"]
    assert fake.calls[1]["tool_choice"] == "none"
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
            model_response(content=final_json()),
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

    with pytest.raises(ReactModelProviderError, match="fallback"):
        await model.decide(context(), ())

    assert [call["model"] for call in fake.calls] == [
        "openai/gpt-5.1",
        "openai/gpt-5-mini",
    ]


@pytest.mark.asyncio
async def test_malformed_envelope_is_response_error_without_fallback() -> None:
    fake = RecordedACompletion([{"choices": []}])
    model = LiteLLMReactModel(
        model="openai/gpt-5.1",
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=30,
        max_retries=1,
        tool_definitions=definitions(),
        acompletion=fake,
    )

    with pytest.raises(ReactModelResponseError, match="envelope"):
        await model.decide(context(), ())

    assert [call["model"] for call in fake.calls] == ["openai/gpt-5.1"]


def test_final_response_schema_recursively_meets_openai_strict_requirements() -> None:
    schema = FinalAgentResponse.model_json_schema()

    def assert_strict_objects(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                assert_strict_objects(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            properties = node.get("properties")
            assert isinstance(properties, dict)
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(properties)
        for value in node.values():
            assert_strict_objects(value)

    assert_strict_objects(schema)


@pytest.mark.parametrize(
    "parameters",
    [
        {"type": "object", "properties": {"query": {"type": "string"}}},
        {"type": "string"},
        {
            "type": "object",
            "properties": {"filters": {"type": ["object", "null"], "properties": {}}},
            "required": ["filters"],
            "additionalProperties": False,
        },
    ],
)
def test_adapter_rejects_non_strict_tool_parameter_schema(
    parameters: dict[str, object],
) -> None:
    loose_definition = ReadOnlyToolDefinition(
        name="loose_tool",
        description="A deliberately invalid tool schema.",
        parameters=parameters,
    )

    with pytest.raises(ValueError, match="strict object schema"):
        LiteLLMReactModel(
            model="openai/gpt-5.1",
            fallback_model="openai/gpt-5-mini",
            reasoning_effort="high",
            timeout_seconds=30,
            max_retries=1,
            tool_definitions=(loose_definition,),
            acompletion=RecordedACompletion([]),
        )


def test_react_settings_have_validated_exact_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "RECIPE_AGENT_LITELLM_CHAT_MODEL",
        "RECIPE_AGENT_LITELLM_FALLBACK_MODEL",
        "RECIPE_AGENT_LITELLM_REASONING_EFFORT",
        "RECIPE_AGENT_LITELLM_TIMEOUT_SECONDS",
        "RECIPE_AGENT_LITELLM_MAX_RETRIES",
        "RECIPE_AGENT_REACT_MAX_ITERATIONS",
    ):
        monkeypatch.delenv(variable, raising=False)
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
