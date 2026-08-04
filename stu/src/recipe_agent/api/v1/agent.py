"""Authenticated private agent-run HTTP API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.conversation.contracts import AgentRunView, ConversationCommand
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.repository import ConversationNotFoundError
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.service import HouseholdScope

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class SubmitRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: UUID | None = None
    message: str = Field(min_length=1)
    locale: Locale
    idempotency_key: str = Field(min_length=1, max_length=160)

    def to_command(self, scope: HouseholdScope, *, transport: str) -> ConversationCommand:
        return ConversationCommand(
            account_id=scope.account_id,
            household_id=scope.household_id,
            conversation_id=self.conversation_id,
            allow_conversation_creation=self.conversation_id is None,
            locale=self.locale,
            message=self.message,
            transport=transport,
            idempotency_key=self.idempotency_key,
        )


def get_conversation_hub(request: Request) -> ConversationHub:
    hub: ConversationHub = request.app.state.conversation_hub
    return hub


HubDependency = Annotated[ConversationHub, Depends(get_conversation_hub)]


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, response_model=AgentRunView)
async def submit_run(
    payload: SubmitRun,
    scope: ScopeDependency,
    hub: HubDependency,
) -> AgentRunView:
    try:
        return await hub.submit_message(payload.to_command(scope, transport="web"))
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.get("/runs/{run_id}", response_model=AgentRunView)
async def get_run(
    run_id: UUID,
    scope: ScopeDependency,
    hub: HubDependency,
) -> AgentRunView:
    run = await hub.get_run(
        run_id,
        account_id=scope.account_id,
        household_id=scope.household_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return run
