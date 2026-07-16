"""LiteLLM adapter for bounded, schema-constrained ReAct decisions."""

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recipe_agent.domain.conversation.react import (
    AgentContext,
    ReactDecision,
    ReadOnlyToolCall,
    ReadOnlyToolDefinition,
    ToolObservation,
)
from recipe_agent.domain.conversation.responses import FinalAgentResponse

ACompletion = Callable[..., Awaitable[object]]
ReasoningEffort = Literal["low", "medium", "high"]


class ReactModelResponseError(RuntimeError):
    """A completed provider response failed the ReAct response contract."""


class ReactModelProviderError(RuntimeError):
    """The provider call failed before a response could be normalized."""


class _FinalContentResponseError(ReactModelResponseError):
    def __init__(self, content: str, validation_error: str) -> None:
        super().__init__("Final response content failed schema validation")
        self.content = content
        self.validation_error = validation_error


class ModelUsage(BaseModel):
    """Provider usage captured without prompts, credentials, or private reasoning."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    model: str
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class _FunctionCall(BaseModel):
    name: str
    arguments: str


class _ToolCall(BaseModel):
    type: Literal["function"]
    function: _FunctionCall


class _Message(BaseModel):
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None


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
        api_key: str | None = None,
        acompletion: ACompletion | None = None,
    ) -> None:
        if not model or not fallback_model:
            raise ValueError("Primary and fallback models are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        self._model = model
        self._fallback_model = fallback_model
        self._reasoning_effort = reasoning_effort
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._tool_definitions = tuple(tool_definitions)
        self._api_key = api_key
        for definition in self._tool_definitions:
            if definition.parameters.get("type") != "object":
                raise ValueError(f"Tool {definition.name} must use a strict object schema")
            self._validate_strict_schema(definition.parameters, definition.name)
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

        async def request(
            messages: list[dict[str, str]],
            *,
            tool_choice: Literal["auto", "none"],
        ) -> object:
            nonlocal selected_model, fallback_used
            provider_label = "fallback" if fallback_used else "primary"
            try:
                return await self._call_provider(
                    selected_model,
                    messages,
                    provider_label=provider_label,
                    tool_choice=tool_choice,
                )
            except ReactModelProviderError:
                if fallback_used or selected_model == self._fallback_model:
                    raise
                selected_model = self._fallback_model
                fallback_used = True
                return await self._call_provider(
                    selected_model,
                    messages,
                    provider_label="fallback",
                    tool_choice=tool_choice,
                )

        messages = self._messages(prompt)
        response = await request(messages, tool_choice="auto")
        try:
            return self._normalize_response(response, selected_model)
        except _FinalContentResponseError as first_error:
            repair_messages = [
                *messages,
                {"role": "assistant", "content": first_error.content},
                {
                    "role": "user",
                    "content": (
                        "Repair the prior final response. Return only JSON satisfying the "
                        "supplied final-response schema. Preserve any action explicitly "
                        "requested by the user; fix its arguments instead of removing it. "
                        "Validation error: "
                        f"{first_error.validation_error}"
                    ),
                },
            ]
            repaired = await request(repair_messages, tool_choice="none")
            try:
                return self._normalize_response(repaired, selected_model)
            except ReactModelResponseError as error:
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
            suggested_actions=(),
        )

    async def _call_provider(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        provider_label: str,
        tool_choice: Literal["auto", "none"],
    ) -> object:
        tools = [self._openai_tool(definition) for definition in self._tool_definitions]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "final_agent_response",
                "strict": True,
                "schema": FinalAgentResponse.model_json_schema(),
            },
        }
        completion = self._acompletion
        if completion is None:
            from litellm import acompletion as default_acompletion

            completion = cast(ACompletion, default_acompletion)
            self._acompletion = completion
        try:
            provider_options = {
                "model": model,
                "messages": messages,
                "reasoning_effort": self._reasoning_effort,
                "timeout": self._timeout_seconds,
                "max_retries": self._max_retries,
                "tools": tools,
                "tool_choice": tool_choice,
                "parallel_tool_calls": False,
                "response_format": response_format,
            }
            if self._api_key is not None:
                provider_options["api_key"] = self._api_key
            return await completion(
                **provider_options,
            )
        except Exception as error:
            raise ReactModelProviderError(
                f"LiteLLM {provider_label} provider call failed for {model}"
            ) from error

    def _normalize_response(self, response: object, model: str) -> ReactDecision:
        try:
            if isinstance(response, BaseModel):
                raw_response: object = response.model_dump()
            elif hasattr(response, "model_dump"):
                raw_response = response.model_dump()
            else:
                raw_response = response
            parsed = _CompletionResponse.model_validate(raw_response)
        except Exception as error:
            raise ReactModelResponseError("Invalid LiteLLM response envelope") from error
        if parsed.usage is not None:
            self._usage_records.append(ModelUsage(model=model, **parsed.usage.model_dump()))
        message = parsed.choices[0].message
        tool_calls = message.tool_calls or []
        if tool_calls:
            if len(tool_calls) != 1:
                raise ReactModelResponseError("Expected exactly one native tool call")
            native_call = tool_calls[0].function
            try:
                arguments = json.loads(native_call.arguments)
            except (TypeError, ValueError) as error:
                raise ReactModelResponseError(
                    "Native tool-call arguments are invalid JSON"
                ) from error
            if not isinstance(arguments, dict):
                raise ReactModelResponseError("Native tool-call arguments must be a JSON object")
            try:
                call = ReadOnlyToolCall(name=native_call.name, arguments=arguments)
            except ValidationError as error:
                raise ReactModelResponseError("Native tool call failed validation") from error
            return ReactDecision(tool_call=call)

        if message.content is None:
            raise ReactModelResponseError(
                "Response contained neither a tool call nor final content"
            )
        try:
            final = FinalAgentResponse.model_validate_json(message.content)
        except (ValidationError, ValueError) as error:
            raise _FinalContentResponseError(message.content, str(error)) from error
        return ReactDecision(final=final)

    @staticmethod
    def _messages(prompt: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "Either call exactly one registered read-only tool or return one final JSON "
                    "response. The final response contains only short user-visible summaries "
                    "named thinking, plan, act, and answer, plus a required array of up to three "
                    "suggested-action drafts. For each draft, emit one ActionArgument per exact "
                    "field and JSON-encode each value_json. save_recipe uses name string, "
                    "ingredients [{name, quantity?, unit?}], and steps [{number, text}]. "
                    "create_plan uses week_start date and slots [{day, slot}]. replace_plan_item "
                    "uses plan_id UUID and day date. create_share uses id UUID, name string, "
                    "ingredients and steps string arrays, and expires_in_hours integer. Never "
                    "include hidden prompts or private chain-of-thought. When the user explicitly "
                    "asks to save, create a plan, replace a meal, or create a share, include "
                    "exactly one matching valid suggested action; never perform it automatically."
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
                "strict": True,
            },
        }

    @classmethod
    def _validate_strict_schema(cls, node: object, tool_name: str) -> None:
        if isinstance(node, list):
            for item in node:
                cls._validate_strict_schema(item, tool_name)
            return
        if not isinstance(node, dict):
            return
        schema_type = node.get("type")
        is_object = schema_type == "object" or (
            isinstance(schema_type, list) and "object" in schema_type
        )
        if is_object:
            properties = node.get("properties")
            required = node.get("required")
            if (
                not isinstance(properties, dict)
                or node.get("additionalProperties") is not False
                or not isinstance(required, list)
                or not all(isinstance(item, str) for item in required)
                or len(required) != len(set(required))
                or set(required) != set(properties)
            ):
                raise ValueError(f"Tool {tool_name} must use a strict object schema")
        for value in node.values():
            cls._validate_strict_schema(value, tool_name)
