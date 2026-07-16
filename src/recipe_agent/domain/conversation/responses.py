"""Safe, transport-neutral responses produced by the conversation agent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.domain.common.types import JsonValue

SuggestedActionType = Literal[
    "save_recipe",
    "create_plan",
    "replace_plan_item",
    "create_share",
]


class SuggestedActionDraft(BaseModel):
    """A validated mutation proposal that still requires explicit user consent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SuggestedActionType
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class FinalAgentResponse(BaseModel):
    """User-visible summaries and answer, never private model reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thinking: str = Field(min_length=1, max_length=800)
    plan: str = Field(min_length=1, max_length=1200)
    act: str = Field(min_length=1, max_length=1200)
    answer: str = Field(min_length=1, max_length=8000)
    suggested_actions: tuple[SuggestedActionDraft, ...] = Field(default=(), max_length=3)
