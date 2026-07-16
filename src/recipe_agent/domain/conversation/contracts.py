"""Typed boundaries for hub-and-spoke agent execution."""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.identity.locale import Locale


class AgentStage(StrEnum):
    """User-visible stages of an agent run."""

    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    ACTING = "acting"
    CHECKING = "checking"
    CONTINUING = "continuing"
    WAITING_FOR_USER = "waiting_for_user"
    FAILED = "failed"
    COMPLETED = "completed"


class RunStatus(StrEnum):
    """Durable lifecycle state for one agent execution."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ConversationCommand(BaseModel):
    """Normalized message received from any transport spoke."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    household_id: UUID
    conversation_id: UUID | None = None
    locale: Locale
    message: str = Field(min_length=1)
    transport: str = "web"
    idempotency_key: str = Field(default_factory=lambda: str(uuid4()))

    @property
    def channel(self) -> str:
        """Compatibility name used by transport adapters."""

        return self.transport

    @property
    def text(self) -> str:
        """Normalized human message text."""

        return self.message


class AgentRunView(BaseModel):
    """Transport-neutral public view of a durable agent run."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    conversation_id: UUID
    account_id: UUID
    household_id: UUID
    transport: str
    status: RunStatus
    response: dict[str, JsonValue] | None = None
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PlannedAction(BaseModel):
    """One bounded tool invocation selected by the planner."""

    model_config = ConfigDict(frozen=True)

    tool_name: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    mutates_state: bool = False


class ToolResult(BaseModel):
    """Verified output returned by a domain tool spoke."""

    model_config = ConfigDict(frozen=True)

    persisted: bool
    data: dict[str, JsonValue] = Field(default_factory=dict)


class AgentProgress(BaseModel):
    """Persistable progress event rendered by each transport."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    stage: AgentStage
    message_key: str
    values: dict[str, JsonValue] = Field(default_factory=dict)


class AgentOutcome(BaseModel):
    """Final machine-readable result of an agent run."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    persisted: bool
    result: dict[str, JsonValue]


class Planner(Protocol):
    async def plan(self, command: ConversationCommand) -> PlannedAction:
        """Select the next bounded action for a command."""


class AgentTool(Protocol):
    async def execute(
        self,
        *,
        command: ConversationCommand,
        action: PlannedAction,
    ) -> ToolResult:
        """Execute a planned domain action."""


class ProgressSink(Protocol):
    async def publish(self, event: AgentProgress) -> None:
        """Publish and persist an agent progress event."""


ToolMap = Mapping[str, AgentTool]
