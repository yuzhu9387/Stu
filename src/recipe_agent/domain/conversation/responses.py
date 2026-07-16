"""Safe, transport-neutral responses produced by the conversation agent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SuggestedActionType = Literal[
    "save_recipe",
    "create_plan",
    "replace_plan_item",
    "create_share",
]


class ActionArgument(BaseModel):
    """One closed, JSON-encoded argument for a proposed mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    value_json: str = Field(min_length=1, max_length=8_000)


class SuggestedActionDraft(BaseModel):
    """A validated mutation proposal that still requires explicit user consent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SuggestedActionType
    arguments: tuple[ActionArgument, ...] = Field(max_length=50)


class FinalAgentResponse(BaseModel):
    """User-visible summaries and answer, never private model reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thinking: str = Field(min_length=1, max_length=800)
    plan: str = Field(min_length=1, max_length=1200)
    act: str = Field(min_length=1, max_length=1200)
    answer: str = Field(min_length=1, max_length=8000)
    suggested_actions: tuple[SuggestedActionDraft, ...] = Field(max_length=3)
