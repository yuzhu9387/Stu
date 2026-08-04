import pytest

from recipe_agent.domain.recipes.contracts import RecipeCandidate
from recipe_agent.infrastructure.ai.litellm_provider import (
    LiteLLMCompletion,
    LiteLLMEmbedding,
    LiteLLMProvider,
    ProviderResponseError,
)


class RecordedCompletion:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return next(self.responses)


@pytest.mark.asyncio
async def test_invalid_extraction_gets_one_repair_request() -> None:
    completion = RecordedCompletion(
        [
            '{"name":"Soup","ingredients":[],"steps":[{"number":1,"text":"Boil"}]}',
            (
                '{"name":"Soup","ingredients":[{"name":"water","quantity":"1",'
                '"unit":"liter"}],"steps":[{"number":1,"text":"Boil"}]}'
            ),
        ]
    )
    provider = LiteLLMProvider(model="openai/gpt-5-mini", completion=completion)

    candidate = await provider.parse_structured("Extract this recipe", RecipeCandidate)

    assert candidate.name == "Soup"
    assert len(completion.calls) == 2
    assert completion.calls[1]["repair"] is True


@pytest.mark.asyncio
async def test_extraction_fails_after_one_repair() -> None:
    completion = RecordedCompletion(["{}", "{}"])
    provider = LiteLLMProvider(model="openai/gpt-5-mini", completion=completion)

    with pytest.raises(ProviderResponseError):
        await provider.parse_structured("Extract this recipe", RecipeCandidate)

    assert len(completion.calls) == 2


@pytest.mark.asyncio
async def test_litellm_completion_extracts_openai_compatible_message_content() -> None:
    calls: list[dict[str, object]] = []

    async def fake_acompletion(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"choices": [{"message": {"content": '{"name":"Soup"}'}}]}

    completion = LiteLLMCompletion(acompletion=fake_acompletion)

    content = await completion(
        model="openai/gpt-5-mini",
        prompt="Extract",
        schema={"type": "object"},
        repair=False,
    )

    assert content == '{"name":"Soup"}'
    assert calls[0]["model"] == "openai/gpt-5-mini"


@pytest.mark.asyncio
async def test_nested_completion_uses_bounded_primary_and_fallback_without_leaking_error() -> None:
    calls: list[dict[str, object]] = []
    private = "provider-secret-payload"

    async def fake_acompletion(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError(private)
        return {"choices": [{"message": {"content": '{"name":"Soup"}'}}]}

    completion = LiteLLMCompletion(
        acompletion=fake_acompletion,
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=12,
        max_retries=2,
        api_key="configured-api-key",
    )
    content = await completion(
        model="openai/gpt-5.1",
        prompt="Extract",
        schema={"type": "object"},
        repair=False,
    )

    assert content == '{"name":"Soup"}'
    assert [call["model"] for call in calls] == ["openai/gpt-5.1", "openai/gpt-5-mini"]
    assert all(call["reasoning_effort"] == "high" for call in calls)
    assert all(call["timeout"] == 12 for call in calls)
    assert all(call["max_retries"] == 2 for call in calls)
    assert all(call["api_key"] == "configured-api-key" for call in calls)


@pytest.mark.asyncio
async def test_nested_completion_sanitizes_provider_and_response_errors() -> None:
    private = "private-provider-response"

    async def fail(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError(private)

    completion = LiteLLMCompletion(
        acompletion=fail,
        fallback_model="openai/gpt-5-mini",
        reasoning_effort="high",
        timeout_seconds=12,
        max_retries=2,
    )
    with pytest.raises(ProviderResponseError) as raised:
        await completion(
            model="openai/gpt-5.1",
            prompt="Extract",
            schema={"type": "object"},
            repair=False,
        )
    assert private not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_provider_routes_embeddings_through_configured_model() -> None:
    calls: list[dict[str, object]] = []

    async def fake_embedding(**kwargs: object) -> list[list[float]]:
        calls.append(kwargs)
        return [[0.1, 0.2]]

    provider = LiteLLMProvider(
        model="openai/gpt-5-mini",
        completion=RecordedCompletion([]),
        embedding_model="openai/text-embedding-3-small",
        embedding=fake_embedding,
    )

    vectors = await provider.embed(["tomato soup"])

    assert vectors == [[0.1, 0.2]]
    assert calls[0]["model"] == "openai/text-embedding-3-small"


@pytest.mark.asyncio
async def test_litellm_embedding_normalizes_openai_compatible_vectors() -> None:
    async def fake_aembedding(**kwargs: object) -> dict[str, object]:
        return {"data": [{"index": 1, "embedding": [0.3]}, {"index": 0, "embedding": [0.1]}]}

    embedding = LiteLLMEmbedding(aembedding=fake_aembedding)

    vectors = await embedding(model="openai/text-embedding-3-small", input=["one", "two"])

    assert vectors == [[0.1], [0.3]]
