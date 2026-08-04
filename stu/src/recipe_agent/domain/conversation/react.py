"""Transport-neutral bounded ReAct state machine."""

import json
from collections.abc import Sequence
from typing import Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.service import HouseholdScope


class UnknownReadOnlyToolError(LookupError):
    """Raised before execution when the model requests an unregistered tool."""


class AgentContext(BaseModel):
    """Private run scope and normalized user input for one reasoning run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    account_id: UUID
    household_id: UUID
    conversation_id: UUID | None = None
    locale: Locale
    message: str = Field(min_length=1)
    transport: str = Field(default="web", min_length=1)

    @classmethod
    def from_command(cls, command: ConversationCommand) -> Self:
        return cls(
            run_id=command.run_id,
            account_id=command.account_id,
            household_id=command.household_id,
            conversation_id=command.conversation_id,
            locale=command.locale,
            message=command.message,
            transport=command.transport,
        )

    @property
    def scope(self) -> HouseholdScope:
        return HouseholdScope(account_id=self.account_id, household_id=self.household_id)


class ReadOnlyToolCall(BaseModel):
    """One model-selected read operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ReadOnlyToolDefinition(BaseModel):
    """OpenAI-compatible metadata for one server-approved read tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    parameters: dict[str, JsonValue]


class ToolObservation(BaseModel):
    """Verified tool output that may be returned to the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=100)
    data: JsonValue
    truncated: bool = False

    def bounded(self, max_chars: int) -> Self:
        """Replace an oversized payload with a hard-bounded serialized preview."""

        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        if len(self.model_dump_json()) <= max_chars:
            return self
        encoded = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        minimal = type(self)(
            tool_name=self.tool_name,
            data=None,
            truncated=True,
        )
        if len(minimal.model_dump_json()) > max_chars:
            raise ValueError("max_chars cannot contain the serialized observation envelope")

        empty_preview = type(self)(
            tool_name=self.tool_name,
            data={"preview": ""},
            truncated=True,
        )
        if len(empty_preview.model_dump_json()) > max_chars:
            return minimal

        best = empty_preview
        low = 0
        high = len(encoded)
        while low <= high:
            midpoint = (low + high) // 2
            candidate = type(self)(
                tool_name=self.tool_name,
                data={"preview": encoded[:midpoint]},
                truncated=True,
            )
            if len(candidate.model_dump_json()) <= max_chars:
                best = candidate
                low = midpoint + 1
            else:
                high = midpoint - 1
        return best


class ReactDecision(BaseModel):
    """Exactly one read-only tool request or one safe final response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call: ReadOnlyToolCall | None = None
    final: FinalAgentResponse | None = None

    @model_validator(mode="after")
    def require_exactly_one_decision(self) -> Self:
        if (self.tool_call is None) == (self.final is None):
            raise ValueError("A decision must contain exactly one tool_call or final response")
        return self


class ReactModel(Protocol):
    async def decide(
        self,
        context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> ReactDecision: ...

    async def finish(
        self,
        context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> FinalAgentResponse: ...


class ReadOnlyToolRegistry(Protocol):
    @property
    def definitions(self) -> Sequence[ReadOnlyToolDefinition]: ...

    async def execute(
        self,
        call: ReadOnlyToolCall,
        scope: HouseholdScope,
    ) -> ToolObservation: ...


class ReactAgent:
    """Execute at most five validated read steps before a conservative finish."""

    def __init__(
        self,
        *,
        model: ReactModel,
        tools: ReadOnlyToolRegistry,
        max_iterations: int = 5,
        max_observation_chars: int = 12_000,
    ) -> None:
        if not 1 <= max_iterations <= 5:
            raise ValueError("max_iterations must be between 1 and 5")
        if max_observation_chars < 1:
            raise ValueError("max_observation_chars must be positive")
        self._model = model
        self._tools = tools
        self._max_iterations = max_iterations
        self._max_observation_chars = max_observation_chars

    async def run(self, context: AgentContext) -> FinalAgentResponse:
        observations: list[ToolObservation] = []
        registered_names = {definition.name for definition in self._tools.definitions}
        for _ in range(self._max_iterations):
            decision = await self._model.decide(context, tuple(observations))
            if decision.final is not None:
                return decision.final
            call = decision.tool_call
            if call is None:
                raise RuntimeError("Validated ReAct decision has no outcome")
            if call.name not in registered_names:
                raise UnknownReadOnlyToolError(f"Unknown read-only tool: {call.name}")
            observation = await self._tools.execute(call, context.scope)
            observations.append(observation.bounded(self._max_observation_chars))
        return await self._model.finish(context, tuple(observations))
