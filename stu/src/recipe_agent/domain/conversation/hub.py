"""Single durable submission boundary shared by every message transport."""

from uuid import UUID

from recipe_agent.domain.conversation.contracts import AgentRunView, ConversationCommand
from recipe_agent.domain.conversation.repository import AgentRunRepository


class ConversationHub:
    """Submit private messages and expose account-scoped runs."""

    def __init__(self, repository: AgentRunRepository) -> None:
        self._repository = repository

    async def submit_message(self, command: ConversationCommand) -> AgentRunView:
        run, _created = await self._repository.create_idempotent(command)
        return run

    async def get_run(
        self,
        run_id: UUID,
        *,
        account_id: UUID,
        household_id: UUID,
    ) -> AgentRunView | None:
        return await self._repository.get_for_account(
            run_id,
            account_id=account_id,
            household_id=household_id,
        )
