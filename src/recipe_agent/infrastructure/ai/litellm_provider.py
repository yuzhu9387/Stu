"""Provider-neutral structured extraction through a LiteLLM-compatible completion."""

from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
Completion = Callable[..., Awaitable[str]]
ACompletion = Callable[..., Awaitable[object]]
Embedding = Callable[..., Awaitable[list[list[float]]]]
AEmbedding = Callable[..., Awaitable[object]]


class ProviderResponseError(RuntimeError):
    """The model failed the structured response contract."""


class _Message(BaseModel):
    content: str


class _Choice(BaseModel):
    message: _Message


class _CompletionResponse(BaseModel):
    choices: list[_Choice]


class _EmbeddingItem(BaseModel):
    index: int
    embedding: list[float]


class _EmbeddingResponse(BaseModel):
    data: list[_EmbeddingItem]


class LiteLLMCompletion:
    """Normalize LiteLLM's OpenAI-compatible response into JSON text."""

    def __init__(self, acompletion: ACompletion | None = None) -> None:
        if acompletion is None:
            from litellm import acompletion as default_acompletion

            acompletion = cast(ACompletion, default_acompletion)
        self._acompletion = acompletion

    async def __call__(
        self,
        *,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
        repair: bool,
        validation_error: str | None = None,
    ) -> str:
        instructions = prompt
        if repair:
            instructions = (
                f"{prompt}\nRepair the prior response to satisfy the schema. "
                f"Validation error: {validation_error}"
            )
        response = await self._acompletion(
            model=model,
            messages=[{"role": "user", "content": instructions}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "structured_result", "schema": dict(schema)},
            },
        )
        if isinstance(response, BaseModel):
            raw_response: object = response.model_dump()
        elif hasattr(response, "model_dump"):
            raw_response = response.model_dump()
        else:
            raw_response = response
        parsed = _CompletionResponse.model_validate(raw_response)
        if not parsed.choices:
            raise ProviderResponseError("LiteLLM returned no choices")
        return parsed.choices[0].message.content


class LiteLLMEmbedding:
    """Normalize LiteLLM embeddings into input order."""

    def __init__(self, aembedding: AEmbedding | None = None) -> None:
        if aembedding is None:
            from litellm import aembedding as default_aembedding

            aembedding = cast(AEmbedding, default_aembedding)
        self._aembedding = aembedding

    async def __call__(self, *, model: str, input: list[str]) -> list[list[float]]:
        response = await self._aembedding(model=model, input=input)
        if isinstance(response, BaseModel):
            raw_response: object = response.model_dump()
        elif hasattr(response, "model_dump"):
            raw_response = response.model_dump()
        else:
            raw_response = response
        parsed = _EmbeddingResponse.model_validate(raw_response)
        return [item.embedding for item in sorted(parsed.data, key=lambda item: item.index)]


class LiteLLMProvider:
    def __init__(
        self,
        *,
        model: str,
        completion: Completion,
        embedding_model: str | None = None,
        embedding: Embedding | None = None,
    ) -> None:
        self._model = model
        self._completion = completion
        self._embedding_model = embedding_model
        self._embedding = embedding

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedding_model is None or self._embedding is None:
            raise RuntimeError("Embedding provider is not configured")
        return await self._embedding(model=self._embedding_model, input=texts)

    async def parse_structured(
        self,
        prompt: str,
        schema: type[StructuredModel],
    ) -> StructuredModel:
        schema_json = schema.model_json_schema()
        response = await self._completion(
            model=self._model,
            prompt=prompt,
            schema=schema_json,
            repair=False,
        )
        try:
            return schema.model_validate_json(response)
        except ValidationError as first_error:
            repaired = await self._completion(
                model=self._model,
                prompt=prompt,
                schema=schema_json,
                repair=True,
                validation_error=str(first_error),
            )
            try:
                return schema.model_validate_json(repaired)
            except ValidationError as error:
                message = "Structured response failed after one repair"
                raise ProviderResponseError(message) from error
