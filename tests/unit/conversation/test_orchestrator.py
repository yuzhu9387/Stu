from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest

from recipe_agent.domain.conversation.contracts import (
    AgentProgress,
    AgentStage,
    ConversationCommand,
    PlannedAction,
    ToolResult,
)
from recipe_agent.domain.conversation.orchestrator import (
    ActionNotPersistedError,
    AgentOrchestrator,
)
from recipe_agent.domain.identity.locale import Locale


class SaveRecipePlanner:
    async def plan(self, command: ConversationCommand) -> PlannedAction:
        return PlannedAction(
            tool_name="save_recipe",
            arguments={"source": command.message},
            mutates_state=True,
        )


class RecordingTool:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[Mapping[str, Any]] = []

    async def execute(
        self,
        *,
        command: ConversationCommand,
        action: PlannedAction,
    ) -> ToolResult:
        self.calls.append(action.arguments)
        return self.result


class RecordingProgressSink:
    def __init__(self) -> None:
        self.events: list[AgentProgress] = []

    async def publish(self, event: AgentProgress) -> None:
        self.events.append(event)


def command_for(message: str) -> ConversationCommand:
    return ConversationCommand(
        account_id=uuid4(),
        household_id=uuid4(),
        conversation_id=uuid4(),
        locale=Locale.EN_US,
        message=message,
    )


@pytest.mark.asyncio
async def test_agent_reports_plan_and_persisted_action_before_success() -> None:
    tool = RecordingTool(result=ToolResult(persisted=True, data={"recipe_id": "r1"}))
    sink = RecordingProgressSink()
    orchestrator = AgentOrchestrator(
        planner=SaveRecipePlanner(),
        tools={"save_recipe": tool},
        progress=sink,
    )

    outcome = await orchestrator.run(command_for("save this recipe"))

    assert [event.stage for event in sink.events] == [
        AgentStage.UNDERSTANDING,
        AgentStage.PLANNING,
        AgentStage.ACTING,
        AgentStage.CHECKING,
        AgentStage.CONTINUING,
    ]
    assert outcome.persisted is True
    assert outcome.result == {"recipe_id": "r1"}
    assert tool.calls == [{"source": "save this recipe"}]


@pytest.mark.asyncio
async def test_agent_rejects_success_for_an_unpersisted_mutation() -> None:
    tool = RecordingTool(result=ToolResult(persisted=False))
    sink = RecordingProgressSink()
    orchestrator = AgentOrchestrator(
        planner=SaveRecipePlanner(),
        tools={"save_recipe": tool},
        progress=sink,
    )

    with pytest.raises(ActionNotPersistedError):
        await orchestrator.run(command_for("save this recipe"))

    assert sink.events[-1].stage is AgentStage.FAILED
