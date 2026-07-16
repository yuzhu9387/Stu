"""Hub orchestrator for action-oriented conversations."""

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.contracts import (
    AgentOutcome,
    AgentProgress,
    AgentStage,
    ConversationCommand,
    Planner,
    ProgressSink,
    ToolMap,
)
from recipe_agent.domain.conversation.tools import ToolRegistry


class ActionNotPersistedError(RuntimeError):
    """Raised when a state-changing tool cannot verify persistence."""


class AgentOrchestrator:
    """Coordinate planning and tool spokes through an auditable state machine."""

    def __init__(self, *, planner: Planner, tools: ToolMap, progress: ProgressSink) -> None:
        self._planner = planner
        self._tools = ToolRegistry(tools)
        self._progress = progress

    async def run(self, command: ConversationCommand) -> AgentOutcome:
        await self._publish(command, AgentStage.UNDERSTANDING)
        await self._publish(command, AgentStage.PLANNING)
        action = await self._planner.plan(command)
        await self._publish(
            command,
            AgentStage.ACTING,
            values={"tool": action.tool_name},
        )

        try:
            result = await self._tools[action.tool_name].execute(command=command, action=action)
            await self._publish(command, AgentStage.CHECKING)
            if action.mutates_state and not result.persisted:
                raise ActionNotPersistedError(
                    f"Tool {action.tool_name} did not verify persistence"
                )
        except Exception:
            await self._publish(command, AgentStage.FAILED)
            raise

        await self._publish(command, AgentStage.CONTINUING)
        return AgentOutcome(
            run_id=command.run_id,
            persisted=result.persisted,
            result=result.data,
        )

    async def _publish(
        self,
        command: ConversationCommand,
        stage: AgentStage,
        *,
        values: dict[str, JsonValue] | None = None,
    ) -> None:
        await self._progress.publish(
            AgentProgress(
                run_id=command.run_id,
                stage=stage,
                message_key=f"agent.stage.{stage.value}",
                values=values or {},
            )
        )
