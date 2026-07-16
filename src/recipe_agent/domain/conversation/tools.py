"""Registry for domain tool spokes."""

from collections.abc import Iterator, Mapping

from recipe_agent.domain.conversation.contracts import AgentTool


class UnknownToolError(LookupError):
    """Raised when the planner selects a tool outside the registry."""


class ToolRegistry(Mapping[str, AgentTool]):
    """Immutable name-to-tool registry."""

    def __init__(self, tools: Mapping[str, AgentTool]) -> None:
        self._tools = dict(tools)

    def __getitem__(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise UnknownToolError(f"Unknown agent tool: {name}") from error

    def __iter__(self) -> Iterator[str]:
        return iter(self._tools)

    def __len__(self) -> int:
        return len(self._tools)
