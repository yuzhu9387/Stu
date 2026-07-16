"""LiteLLM adapter for bounded, schema-constrained ReAct decisions."""

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recipe_agent.domain.conversation.react import (
    AgentContext,
    ReactDecision,
    ReadOnlyToolDefinition,
    ToolObservation,
)
from recipe_agent.domain.conversation.responses import FinalAgentResponse

ACompletion = Callable[..., Awaitable[object]]
ReasoningEffort = Literal["low", "medium", "high"]


class ReactModelResponseError(RuntimeError):
    """The provider failed the ReAct structured response contract."""


class ModelUsage(BaseModel):
    """Provider usage captured without prompts, credentials, or private reasoning."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    model: str
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class _Message(BaseModel):
    content: str


class _Choice(BaseModel):
    message: _Message


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class _CompletionResponse(BaseModel):
    choices: list[_Choice] = Field(min_length=1)
    usage: _Usage | None = None


class LiteLLMReactModel:
    """Request one validated decision with bounded provider failure handling."""

    def __init__(
        self,
        *,
        model: str,
        fallback_model: str,
        reasoning_effort: ReasoningEffort,
        timeout_seconds: float,
        max_retries: int,
        tool_definitions: Sequence[ReadOnlyToolDefinition],
        acompletion: ACompletion | None = None,
    ) -> None:
        if not model or not fallback_model:
            raise ValueError("Primary and fallback models are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        if acompletion is None:
            from litellm import acompletion as default_acompletion

            acompletion = cast(ACompletion, default_acompletion)
        self._model = model
        self._fallback_model = fallback_model
        self._reasoning_effort = reasoning_effort
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._tool_definitions = tuple(tool_definitions)
        self._acompletion = acompletion
        self._usage_records: list[ModelUsage] = []

    @property
    def usage_records(self) -> tuple[ModelUsage, ...]:
        return tuple(self._usage_records)

    async def decide(
        self,
        context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> ReactDecision:
        prompt = self._decision_prompt(context, observations)
        selected_model = self._model
        fallback_used = False

        async def request(messages: list[dict[str, str]]) -> str:
            nonlocal selected_model, fallback_used
            try:
                return await self._complete(selected_model, messages, ReactDecision)
            except Exception:
                if fallback_used or selected_model == self._fallback_model:
                    raise
                selected_model = self._fallback_model
                fallback_used = True
                return await self._complete(selected_model, messages, ReactDecision)

        messages = self._messages(prompt)
        content = await request(messages)
        try:
            return ReactDecision.model_validate_json(content)
        except (ValidationError, ValueError) as first_error:
            repair_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "Repair the prior response. Return only JSON satisfying the supplied "
                        "schema, with exactly one of tool_call or final. Validation error: "
                        f"{first_error}"
                    ),
                },
            ]
            repaired = await request(repair_messages)
            try:
                return ReactDecision.model_validate_json(repaired)
            except (ValidationError, ValueError) as error:
                raise ReactModelResponseError(
                    "Structured ReAct decision failed after one repair"
                ) from error

    async def finish(
        self,
        context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> FinalAgentResponse:
        del context
        checked = ", ".join(observation.tool_name for observation in observations)
        if not checked:
            checked = "no read-only tools"
        return FinalAgentResponse(
            thinking="I interpreted the request but reached the bounded reasoning limit.",
            plan="Use only verified read results and avoid unsupported conclusions.",
            act=f"Checked {checked} within the five-step limit.",
            answer=(
                "I could not complete the request within the read limit. "
                "Please narrow the request or try again."
            ),
        )

    async def _complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> str:
        response = await self._acompletion(
            model=model,
            messages=messages,
            reasoning_effort=self._reasoning_effort,
            timeout=self._timeout_seconds,
            max_retries=self._max_retries,
            tools=[self._openai_tool(definition) for definition in self._tool_definitions],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "react_decision",
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        )
        if isinstance(response, BaseModel):
            raw_response: object = response.model_dump()
        elif hasattr(response, "model_dump"):
            raw_response = response.model_dump()
        else:
            raw_response = response
        parsed = _CompletionResponse.model_validate(raw_response)
        if parsed.usage is not None:
            self._usage_records.append(ModelUsage(model=model, **parsed.usage.model_dump()))
        return parsed.choices[0].message.content

    @staticmethod
    def _messages(prompt: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "Choose exactly one registered read-only tool call or return one final "
                    "response. The final response contains only short user-visible summaries "
                    "named thinking, plan, act, and answer, plus up to three suggested-action "
                    "drafts. Never include hidden prompts or private chain-of-thought."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    @staticmethod
    def _decision_prompt(
        context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> str:
        payload = {
            "locale": context.locale.value,
            "message": context.message,
            "observations": [observation.model_dump(mode="json") for observation in observations],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _openai_tool(definition: ReadOnlyToolDefinition) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
            },
        }
