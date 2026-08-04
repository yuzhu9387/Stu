"""Safe, transport-neutral responses produced by the conversation agent."""

import json
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from recipe_agent.domain.planning.contracts import PlanSlot
from recipe_agent.domain.recipes.contracts import RecipeCandidate

SuggestedActionType = Literal[
    "save_recipe",
    "create_plan",
    "replace_plan_item",
    "create_share",
]


class _SaveRecipeArguments(RecipeCandidate):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CreatePlanArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: date
    slots: tuple[PlanSlot, ...]


class _ReplacePlanItemArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID
    day: date


class _CreateShareArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str = Field(min_length=1)
    ingredients: tuple[str, ...]
    steps: tuple[str, ...]
    expires_in_hours: int = Field(ge=1, le=24 * 30)


_ACTION_ARGUMENT_MODELS: dict[SuggestedActionType, type[BaseModel]] = {
    "save_recipe": _SaveRecipeArguments,
    "create_plan": _CreatePlanArguments,
    "replace_plan_item": _ReplacePlanItemArguments,
    "create_share": _CreateShareArguments,
}
_ACTION_ARGUMENT_CONTRACTS: dict[SuggestedActionType, str] = {
    "save_recipe": (
        "name is a JSON string; ingredients is a JSON array of objects with name and optional "
        "quantity/unit; steps is a JSON array of objects with integer number and text"
    ),
    "create_plan": (
        "week_start is a JSON date string; slots is a JSON array of objects with day and slot"
    ),
    "replace_plan_item": "plan_id is a JSON UUID string; day is a JSON date string",
    "create_share": (
        "id is a JSON UUID string; name is a JSON string; ingredients and steps are JSON "
        "string arrays; expires_in_hours is a JSON integer from 1 to 720"
    ),
}


class ActionArgument(BaseModel):
    """One closed, JSON-encoded argument for a proposed mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    value_json: str = Field(min_length=1, max_length=8_000)


class SuggestedActionDraft(BaseModel):
    """A validated mutation proposal that still requires explicit user consent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SuggestedActionType
    arguments: tuple[ActionArgument, ...] = Field(
        max_length=50,
        description=(
            "One entry per exact action field. JSON-encode every value_json. save_recipe: name "
            "string, ingredients [{name, quantity?, unit?}], steps [{number, text}]. create_plan: "
            "week_start date, slots [{day, slot}]. replace_plan_item: plan_id UUID, day date. "
            "create_share: id UUID, name string, ingredients [string], steps [string], "
            "expires_in_hours integer."
        ),
    )

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "SuggestedActionDraft":
        decoded: dict[str, object] = {}
        expected_model = _ACTION_ARGUMENT_MODELS[self.type]
        expected_fields = ", ".join(expected_model.model_fields)
        contract = _ACTION_ARGUMENT_CONTRACTS[self.type]
        for argument in self.arguments:
            if argument.name in decoded:
                raise ValueError(f"{self.type} contains a duplicate {argument.name} argument")
            try:
                decoded[argument.name] = json.loads(argument.value_json)
            except json.JSONDecodeError:
                raise ValueError(f"{self.type}.{argument.name} must contain valid JSON") from None
        try:
            expected_model.model_validate(decoded)
        except ValidationError:
            raise ValueError(
                f"{self.type} requires one JSON argument per field: {expected_fields}. "
                f"Field contract: {contract}"
            ) from None
        return self


class FinalAgentResponse(BaseModel):
    """User-visible summaries and answer, never private model reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thinking: str = Field(min_length=1, max_length=800)
    plan: str = Field(min_length=1, max_length=1200)
    act: str = Field(min_length=1, max_length=1200)
    answer: str = Field(min_length=1, max_length=8000)
    suggested_actions: tuple[SuggestedActionDraft, ...] = Field(max_length=3)
