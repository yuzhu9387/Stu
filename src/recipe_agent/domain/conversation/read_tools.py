"""Concrete, strictly validated read-only tools for the bounded ReAct runtime."""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.react import (
    ReadOnlyToolCall,
    ReadOnlyToolDefinition,
    ToolObservation,
    UnknownReadOnlyToolError,
)
from recipe_agent.domain.identity.preferences import DietaryPreferenceView
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.imports.contracts import InputKind
from recipe_agent.domain.planning.contracts import MealPlan, MealPlanSummary, ShoppingListView
from recipe_agent.domain.recipes.contracts import RecipeCandidate, RecipeSummary
from recipe_agent.domain.recommendations.contracts import RecommendationQuery, RecommendationSource
from recipe_agent.domain.recommendations.service import RecommendationService


class InvalidReadOnlyToolArgumentsError(ValueError):
    """A registered tool was called with arguments outside its closed schema."""


class InvalidRecommendationOwnershipError(RuntimeError):
    """A household recommendation is missing required ownership metadata."""


class RecipeQueries(Protocol):
    async def search_owned(
        self, scope: HouseholdScope, query: str
    ) -> tuple[RecipeSummary, ...]: ...

    async def search_family(
        self, scope: HouseholdScope, query: str
    ) -> tuple[RecipeSummary, ...]: ...


class SettingsQueries(Protocol):
    async def list_for_scope(self, scope: HouseholdScope) -> tuple[DietaryPreferenceView, ...]: ...


class PlanQueries(Protocol):
    async def list_for_scope(self, scope: HouseholdScope) -> tuple[MealPlanSummary, ...]: ...

    async def get_for_scope(self, scope: HouseholdScope, plan_id: UUID) -> MealPlanSummary: ...


class ShoppingQueries(Protocol):
    async def list_shopping_for_scope(
        self, scope: HouseholdScope
    ) -> tuple[ShoppingListView, ...]: ...


class ImportPreviewService(Protocol):
    async def preview(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        kind: InputKind,
        source: str,
    ) -> RecipeCandidate: ...


class PlanningPreviewService(Protocol):
    async def preview_replace_item(self, plan: MealPlan, day: date) -> MealPlan: ...


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SearchArguments(_Arguments):
    query: str = Field(default="", max_length=300)


class _NoArguments(_Arguments):
    pass


class _RecommendationArguments(_Arguments):
    ingredients: frozenset[str] = frozenset()
    allergies: frozenset[str] = frozenset()
    age_years: int | None = Field(default=None, ge=0)
    meal_type: str | None = None
    maximum_minutes: int | None = Field(default=None, ge=1)


class _ImportPreviewArguments(_Arguments):
    kind: InputKind
    source: str = Field(min_length=1, max_length=20_000)


class _PlanPreviewArguments(_Arguments):
    plan_id: UUID
    day: date


_ARGUMENT_MODELS: dict[str, type[_Arguments]] = {
    "search_own_recipes": _SearchArguments,
    "search_family_recipes": _SearchArguments,
    "read_dietary_preferences": _NoArguments,
    "read_plans": _NoArguments,
    "read_shopping_lists": _NoArguments,
    "recommend_three": _RecommendationArguments,
    "preview_recipe_import": _ImportPreviewArguments,
    "preview_plan_change": _PlanPreviewArguments,
}

_DESCRIPTIONS = {
    "search_own_recipes": "Search recipes owned by the requesting account in its current family.",
    "search_family_recipes": "Search family-visible recipes and retain their owners.",
    "read_dietary_preferences": "Read personal and family-visible dietary preferences.",
    "read_plans": "Read current-family meal plans without changing them.",
    "read_shopping_lists": "Read current-family shopping lists without changing them.",
    "recommend_three": "Return exactly three eligible recommendations or a capacity error.",
    "preview_recipe_import": "Parse a recipe import preview without saving source data.",
    "preview_plan_change": "Preview one plan replacement without saving it.",
}


class ReadOnlyToolRegistry:
    """The eight approved read tools; no arbitrary callable registration is supported."""

    def __init__(
        self,
        *,
        recipe_queries: RecipeQueries,
        settings_queries: SettingsQueries,
        plan_queries: PlanQueries,
        shopping_queries: ShoppingQueries,
        recommendation_service: RecommendationService,
        import_service: ImportPreviewService,
        planning_service: PlanningPreviewService,
    ) -> None:
        self._recipe_queries = recipe_queries
        self._settings_queries = settings_queries
        self._plan_queries = plan_queries
        self._shopping_queries = shopping_queries
        self._recommendation_service = recommendation_service
        self._import_service = import_service
        self._planning_service = planning_service

    @classmethod
    def tool_definitions(cls) -> Mapping[str, ReadOnlyToolDefinition]:
        return {
            name: ReadOnlyToolDefinition(
                name=name,
                description=_DESCRIPTIONS[name],
                parameters=_strict_schema(model.model_json_schema()),
            )
            for name, model in _ARGUMENT_MODELS.items()
        }

    @property
    def definitions(self) -> Sequence[ReadOnlyToolDefinition]:
        return tuple(self.tool_definitions().values())

    async def execute(self, call: ReadOnlyToolCall, scope: HouseholdScope) -> ToolObservation:
        argument_model = _ARGUMENT_MODELS.get(call.name)
        if argument_model is None:
            raise UnknownReadOnlyToolError(f"Unknown read-only tool: {call.name}")
        try:
            arguments = argument_model.model_validate(call.arguments)
        except ValidationError as error:
            raise InvalidReadOnlyToolArgumentsError(
                f"Invalid arguments for read-only tool: {call.name}"
            ) from error

        data: JsonValue
        if call.name == "search_own_recipes":
            search = _as(arguments, _SearchArguments)
            data = {"recipes": _dump(await self._recipe_queries.search_owned(scope, search.query))}
        elif call.name == "search_family_recipes":
            search = _as(arguments, _SearchArguments)
            data = {"recipes": _dump(await self._recipe_queries.search_family(scope, search.query))}
        elif call.name == "read_dietary_preferences":
            data = {"preferences": _dump(await self._settings_queries.list_for_scope(scope))}
        elif call.name == "read_plans":
            data = {"plans": _dump(await self._plan_queries.list_for_scope(scope))}
        elif call.name == "read_shopping_lists":
            data = {
                "shopping_lists": _dump(await self._shopping_queries.list_shopping_for_scope(scope))
            }
        elif call.name == "recommend_three":
            recommendation = _as(arguments, _RecommendationArguments)
            results = await self._recommendation_service.recommend(
                RecommendationQuery(
                    household_id=scope.household_id,
                    ingredients=recommendation.ingredients,
                    allergies=recommendation.allergies,
                    age_years=recommendation.age_years,
                    meal_type=recommendation.meal_type,
                    maximum_minutes=recommendation.maximum_minutes,
                )
            )
            recommendations = _dump(results)
            for result, item in zip(results, recommendations, strict=True):
                if (
                    result.source is RecommendationSource.HOUSEHOLD
                    and result.owner_account_id is None
                ):
                    raise InvalidRecommendationOwnershipError(
                        "Household recommendation is missing its owner"
                    )
                if (
                    result.source is RecommendationSource.GENERATED
                    and result.owner_account_id is None
                    and isinstance(item, dict)
                ):
                    item["owner_account_id"] = str(scope.account_id)
            data = {"recommendations": recommendations}
        elif call.name == "preview_recipe_import":
            import_preview = _as(arguments, _ImportPreviewArguments)
            candidate = await self._import_service.preview(
                scope.account_id,
                scope.household_id,
                import_preview.kind,
                import_preview.source,
            )
            data = cast(
                JsonValue,
                {
                    "recipe": {
                        **candidate.model_dump(mode="json"),
                        "owner_account_id": str(scope.account_id),
                    }
                },
            )
        else:
            plan_preview = _as(arguments, _PlanPreviewArguments)
            plan = await self._plan_queries.get_for_scope(scope, plan_preview.plan_id)
            proposed = await self._planning_service.preview_replace_item(plan, plan_preview.day)
            data = cast(JsonValue, {"plan": proposed.model_dump(mode="json")})
        return ToolObservation(tool_name=call.name, data=data)


def _as[T: _Arguments](value: _Arguments, expected: type[T]) -> T:
    if not isinstance(value, expected):
        raise TypeError("Validated tool arguments have an unexpected model")
    return value


def _dump(values: Sequence[BaseModel]) -> list[JsonValue]:
    return [cast(JsonValue, value.model_dump(mode="json")) for value in values]


def _strict_schema(schema: dict[str, Any]) -> dict[str, JsonValue]:
    def close(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                close(item)
            return
        if not isinstance(node, dict):
            return
        # Pydantic emits validation and presentation keywords that OpenAI's
        # strict function-tool schema does not accept. Runtime Pydantic models
        # still enforce uniqueness and defaults after the model returns args.
        for unsupported_keyword in ("default", "title", "uniqueItems"):
            node.pop(unsupported_keyword, None)
        if node.get("type") == "object":
            properties = node.get("properties", {})
            if isinstance(properties, dict):
                node["additionalProperties"] = False
                node["required"] = list(properties)
        for child in node.values():
            close(child)

    close(schema)
    return cast(dict[str, JsonValue], schema)
