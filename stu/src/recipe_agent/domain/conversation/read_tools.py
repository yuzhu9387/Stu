"""Concrete, strictly validated read-only tools for the bounded ReAct runtime."""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

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
from recipe_agent.domain.planning.contracts import (
    MealPlan,
    MealPlanSummary,
    PlanItem,
    PlanSlot,
    ShoppingListView,
)
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeDetail,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
    RecipeSummary,
    RecipeView,
)
from recipe_agent.domain.recommendations.contracts import RecommendationQuery, RecommendationSource
from recipe_agent.domain.recommendations.service import RecommendationService
from recipe_agent.domain.todos.contracts import TodoCreate, TodoUpdate, TodoView


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

    async def create(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        candidate: RecipeCandidate,
        *,
        source_action_id: UUID | None = None,
        visibility: str = "family",
        meal_type: str = "dinner",
        prep_minutes: int = 0,
        cook_minutes: int = 0,
        suitable_age_years: int = 0,
        image_url: str | None = None,
    ) -> RecipeView: ...

    async def update_for_owner(
        self,
        scope: HouseholdScope,
        recipe_id: UUID,
        candidate: RecipeCandidate,
        *,
        visibility: str,
        meal_type: str,
        prep_minutes: int,
        cook_minutes: int,
        suitable_age_years: int,
        image_url: str | None,
    ) -> RecipeDetail: ...

    async def delete_for_owner(self, scope: HouseholdScope, recipe_id: UUID) -> None: ...


class SettingsQueries(Protocol):
    async def list_for_scope(self, scope: HouseholdScope) -> tuple[DietaryPreferenceView, ...]: ...


class PlanQueries(Protocol):
    async def list_for_scope(self, scope: HouseholdScope) -> tuple[MealPlanSummary, ...]: ...

    async def get_for_scope(self, scope: HouseholdScope, plan_id: UUID) -> MealPlanSummary: ...

    async def update_metadata_for_owner(
        self,
        scope: HouseholdScope,
        plan_id: UUID,
        *,
        title: str | None = None,
        week_start: date | None = None,
    ) -> MealPlanSummary: ...

    async def add_item_for_owner(
        self, scope: HouseholdScope, plan_id: UUID, item: PlanItem
    ) -> MealPlanSummary: ...

    async def update_item_for_owner(
        self, scope: HouseholdScope, plan_id: UUID, item_id: UUID, item: PlanItem
    ) -> MealPlanSummary: ...

    async def delete_item_for_owner(
        self, scope: HouseholdScope, plan_id: UUID, item_id: UUID
    ) -> MealPlanSummary: ...

    async def delete_for_owner(self, scope: HouseholdScope, plan_id: UUID) -> None: ...


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

    async def create_week(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        week_start: date,
        slots: tuple[PlanSlot, ...],
        *,
        source_action_id: UUID | None = None,
        title: str = "Weekly plan",
        generated_by_ai: bool = False,
    ) -> MealPlan: ...


class TodoQueries(Protocol):
    async def list_for_scope(self, scope: HouseholdScope) -> tuple[TodoView, ...]: ...

    async def create(self, scope: HouseholdScope, payload: TodoCreate) -> TodoView: ...

    async def update(
        self, scope: HouseholdScope, todo_id: UUID, payload: TodoUpdate
    ) -> TodoView: ...

    async def delete(self, scope: HouseholdScope, todo_id: UUID) -> None: ...


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


class _IngredientArguments(_Arguments):
    name: str = Field(min_length=1, max_length=300)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=64)


class _StepArguments(_Arguments):
    number: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)


class _RecipeMutationArguments(_Arguments):
    name: str = Field(min_length=1, max_length=300)
    meal_type: str = Field(default="dinner", min_length=1, max_length=32)
    prep_minutes: int = Field(default=0, ge=0, le=1440)
    cook_minutes: int = Field(default=0, ge=0, le=1440)
    suitable_age_years: int = Field(default=0, ge=0, le=120)
    visibility: str = Field(default="family", pattern="^(private|family)$")
    image_url: str | None = Field(default=None, max_length=2000)
    ingredients: tuple[_IngredientArguments, ...] = ()
    steps: tuple[_StepArguments, ...] = ()

    def candidate(self) -> RecipeCandidate:
        return RecipeCandidate(
            name=self.name,
            ingredients=tuple(
                RecipeIngredientCandidate(**item.model_dump()) for item in self.ingredients
            ),
            steps=tuple(RecipeStepCandidate(**item.model_dump()) for item in self.steps),
        )


class _UpdateRecipeArguments(_RecipeMutationArguments):
    recipe_id: UUID


class _IdArguments(_Arguments):
    id: UUID


class _CreatePlanArguments(_Arguments):
    title: str = Field(default="AI weekly plan", min_length=1, max_length=200)
    week_start: date
    slots: tuple[PlanSlot, ...] = Field(min_length=1, max_length=21)


class _UpdatePlanArguments(_Arguments):
    plan_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    week_start: date | None = None


class _PlanItemArguments(_Arguments):
    plan_id: UUID
    item_id: UUID | None = None
    day: date
    slot: str = Field(min_length=1, max_length=32)
    recipe_id: UUID
    recipe_name: str = Field(min_length=1, max_length=300)

    def item(self) -> PlanItem:
        return PlanItem(
            id=self.item_id or uuid4(),
            day=self.day,
            slot=self.slot,
            recipe_id=self.recipe_id,
            recipe_name=self.recipe_name,
            reason_codes=("agent_selected",),
        )


class _DeletePlanItemArguments(_Arguments):
    plan_id: UUID
    item_id: UUID


class _CreateTodoArguments(_Arguments):
    category: Literal["grocery", "todo"]
    title: str = Field(min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    due_on: date | None = None
    visibility: Literal["private", "family"] = "family"


class _UpdateTodoArguments(_Arguments):
    todo_id: UUID
    category: Literal["grocery", "todo"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    completed: bool | None = None
    due_on: date | None = None
    visibility: Literal["private", "family"] | None = None


_ARGUMENT_MODELS: dict[str, type[_Arguments]] = {
    "search_own_recipes": _SearchArguments,
    "search_family_recipes": _SearchArguments,
    "read_dietary_preferences": _NoArguments,
    "read_plans": _NoArguments,
    "read_shopping_lists": _NoArguments,
    "recommend_three": _RecommendationArguments,
    "preview_recipe_import": _ImportPreviewArguments,
    "preview_plan_change": _PlanPreviewArguments,
    "create_recipe": _RecipeMutationArguments,
    "update_recipe": _UpdateRecipeArguments,
    "delete_recipe": _IdArguments,
    "create_plan": _CreatePlanArguments,
    "update_plan": _UpdatePlanArguments,
    "delete_plan": _IdArguments,
    "add_plan_item": _PlanItemArguments,
    "update_plan_item": _PlanItemArguments,
    "delete_plan_item": _DeletePlanItemArguments,
    "read_todos": _NoArguments,
    "create_todo": _CreateTodoArguments,
    "update_todo": _UpdateTodoArguments,
    "delete_todo": _IdArguments,
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
    "create_recipe": (
        "Create a recipe owned by the requesting account immediately when explicitly requested."
    ),
    "update_recipe": "Update a recipe owned by the requesting account immediately.",
    "delete_recipe": "Delete a recipe owned by the requesting account immediately.",
    "create_plan": "Generate and save a meal plan owned by the requesting account immediately.",
    "update_plan": "Update an owned meal plan title or week immediately.",
    "delete_plan": "Delete a meal plan owned by the requesting account immediately.",
    "add_plan_item": "Add a meal item to an owned plan immediately.",
    "update_plan_item": "Update an existing meal item in an owned plan immediately.",
    "delete_plan_item": "Delete an existing meal item from an owned plan immediately.",
    "read_todos": "Read current family-visible grocery and todo entries.",
    "create_todo": "Create a grocery or todo entry owned by the requesting account immediately.",
    "update_todo": "Update an owned grocery or todo entry immediately.",
    "delete_todo": "Delete an owned grocery or todo entry immediately.",
}


class ReadOnlyToolRegistry:
    """Closed, account-scoped tool registry shared by Web and Lark agents."""

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
        todo_queries: TodoQueries,
    ) -> None:
        self._recipe_queries = recipe_queries
        self._settings_queries = settings_queries
        self._plan_queries = plan_queries
        self._shopping_queries = shopping_queries
        self._recommendation_service = recommendation_service
        self._import_service = import_service
        self._planning_service = planning_service
        self._todo_queries = todo_queries

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
            for result, recommendation_payload in zip(results, recommendations, strict=True):
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
                    and isinstance(recommendation_payload, dict)
                ):
                    recommendation_payload["owner_account_id"] = str(scope.account_id)
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
        elif call.name == "preview_plan_change":
            plan_preview = _as(arguments, _PlanPreviewArguments)
            preview_plan = await self._plan_queries.get_for_scope(scope, plan_preview.plan_id)
            proposed = await self._planning_service.preview_replace_item(
                preview_plan, plan_preview.day
            )
            data = cast(JsonValue, {"plan": proposed.model_dump(mode="json")})
        elif call.name == "create_recipe":
            recipe = _as(arguments, _RecipeMutationArguments)
            created = await self._recipe_queries.create(
                scope.account_id,
                scope.household_id,
                recipe.candidate(),
                visibility=recipe.visibility,
                meal_type=recipe.meal_type,
                prep_minutes=recipe.prep_minutes,
                cook_minutes=recipe.cook_minutes,
                suitable_age_years=recipe.suitable_age_years,
                image_url=recipe.image_url,
            )
            data = cast(JsonValue, {"recipe": created.model_dump(mode="json")})
        elif call.name == "update_recipe":
            recipe = _as(arguments, _UpdateRecipeArguments)
            updated = await self._recipe_queries.update_for_owner(
                scope,
                recipe.recipe_id,
                recipe.candidate(),
                visibility=recipe.visibility,
                meal_type=recipe.meal_type,
                prep_minutes=recipe.prep_minutes,
                cook_minutes=recipe.cook_minutes,
                suitable_age_years=recipe.suitable_age_years,
                image_url=recipe.image_url,
            )
            data = cast(JsonValue, {"recipe": updated.model_dump(mode="json")})
        elif call.name == "delete_recipe":
            target = _as(arguments, _IdArguments)
            await self._recipe_queries.delete_for_owner(scope, target.id)
            data = {"deleted_recipe_id": str(target.id)}
        elif call.name == "create_plan":
            create_plan_args = _as(arguments, _CreatePlanArguments)
            created_plan = await self._planning_service.create_week(
                scope.account_id,
                scope.household_id,
                create_plan_args.week_start,
                create_plan_args.slots,
                title=create_plan_args.title,
                generated_by_ai=True,
            )
            data = cast(JsonValue, {"plan": created_plan.model_dump(mode="json")})
        elif call.name == "update_plan":
            update_plan_args = _as(arguments, _UpdatePlanArguments)
            updated_plan = await self._plan_queries.update_metadata_for_owner(
                scope,
                update_plan_args.plan_id,
                title=update_plan_args.title,
                week_start=update_plan_args.week_start,
            )
            data = cast(JsonValue, {"plan": updated_plan.model_dump(mode="json")})
        elif call.name == "delete_plan":
            target = _as(arguments, _IdArguments)
            await self._plan_queries.delete_for_owner(scope, target.id)
            data = {"deleted_plan_id": str(target.id)}
        elif call.name in {"add_plan_item", "update_plan_item"}:
            plan_item_args = _as(arguments, _PlanItemArguments)
            if call.name == "add_plan_item":
                updated_plan = await self._plan_queries.add_item_for_owner(
                    scope, plan_item_args.plan_id, plan_item_args.item()
                )
            else:
                if plan_item_args.item_id is None:
                    raise InvalidReadOnlyToolArgumentsError("update_plan_item requires item_id")
                updated_plan = await self._plan_queries.update_item_for_owner(
                    scope,
                    plan_item_args.plan_id,
                    plan_item_args.item_id,
                    plan_item_args.item(),
                )
            data = cast(JsonValue, {"plan": updated_plan.model_dump(mode="json")})
        elif call.name == "delete_plan_item":
            delete_plan_item_args = _as(arguments, _DeletePlanItemArguments)
            updated_plan = await self._plan_queries.delete_item_for_owner(
                scope, delete_plan_item_args.plan_id, delete_plan_item_args.item_id
            )
            data = cast(JsonValue, {"plan": updated_plan.model_dump(mode="json")})
        elif call.name == "read_todos":
            data = {"todos": _dump(await self._todo_queries.list_for_scope(scope))}
        elif call.name == "create_todo":
            create_todo_args = _as(arguments, _CreateTodoArguments)
            created_todo = await self._todo_queries.create(
                scope,
                TodoCreate(**create_todo_args.model_dump()),
            )
            data = cast(JsonValue, {"todo": created_todo.model_dump(mode="json")})
        elif call.name == "update_todo":
            update_todo_args = _as(arguments, _UpdateTodoArguments)
            updated_todo = await self._todo_queries.update(
                scope,
                update_todo_args.todo_id,
                TodoUpdate(**update_todo_args.model_dump(exclude={"todo_id"})),
            )
            data = cast(JsonValue, {"todo": updated_todo.model_dump(mode="json")})
        else:
            target = _as(arguments, _IdArguments)
            await self._todo_queries.delete(scope, target.id)
            data = {"deleted_todo_id": str(target.id)}
        return ToolObservation(tool_name=call.name, data=data)


def _as[T: _Arguments](value: _Arguments, expected: type[T]) -> T:
    if not isinstance(value, expected):
        raise TypeError("Validated tool arguments have an unexpected model")
    return value


def _dump(values: Sequence[BaseModel]) -> list[JsonValue]:
    return [cast(JsonValue, value.model_dump(mode="json")) for value in values]


def _strict_schema(schema: dict[str, Any]) -> dict[str, JsonValue]:
    def close(node: object, *, property_map: bool = False) -> None:
        if isinstance(node, list):
            for item in node:
                close(item)
            return
        if not isinstance(node, dict):
            return
        # Pydantic emits validation and presentation keywords that OpenAI's
        # strict function-tool schema does not accept. Runtime Pydantic models
        # still enforce uniqueness and defaults after the model returns args.
        unsupported_keywords = ("default", "uniqueItems") if property_map else (
            "default",
            "title",
            "uniqueItems",
        )
        for unsupported_keyword in unsupported_keywords:
            node.pop(unsupported_keyword, None)
        if node.get("type") == "object":
            properties = node.get("properties", {})
            if isinstance(properties, dict):
                node["additionalProperties"] = False
                node["required"] = list(properties)
        for key, child in node.items():
            close(child, property_map=key == "properties")

    close(schema)
    return cast(dict[str, JsonValue], schema)
