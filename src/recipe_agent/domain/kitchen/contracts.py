"""Strict camelCase transport and persistence contracts."""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, Protocol, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
FoodType = Literal["Protein", "Carbs", "Vegetables", "Dairy", "Other"]
Slot = Literal["breakfast", "lunch", "dinner"]
Status = Literal["planned", "completed", "skipped"]
# The angles a plan can be analysed from. The catalog is fixed; a household
# chooses which of them its plan analysis shows. Order is the display order.
AnalysisMetric = Literal[
    "prep_time", "daily_time", "nutrition_balance", "repetition", "fridge_usage"
]
ANALYSIS_METRICS: tuple[AnalysisMetric, ...] = (
    "prep_time",
    "daily_time",
    "nutrition_balance",
    "repetition",
    "fridge_usage",
)
TagName = Annotated[str, Field(min_length=1, max_length=100)]
# Pinned until the household chooses: the three meals (by slot) and the
# child's tags, which lead the Recipe Book filters as large chips.
DEFAULT_PINNED_TAGS: tuple[str, ...] = ("breakfast", "lunch", "dinner", "小孩饭", "Baby-friendly")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Ingredient(Contract):
    name: Identifier
    quantity: Number
    unit: str
    # 肉类 / 辅料 / 调味糖色 / 调味料 grouping on frame 36:1030.
    group: str | None = Field(default=None, max_length=60)


class StepDetail(Contract):
    """Optional annotation for one step of a recipe, from frame 36:1030.

    Steps stay plain strings so AI generation, extraction and existing records
    keep working unchanged; this carries the title and timing the detail screen
    adds, addressed by index rather than by position in a parallel array.
    """

    index: int = Field(ge=0)
    title: str | None = Field(default=None, max_length=200)
    titleEn: str | None = Field(default=None, max_length=200)
    activeMinutes: Number | None = None
    waitMinutes: Number | None = None


class ReheatInstruction(Contract):
    method: Literal["microwave", "steamer", "pan", "oven", "other"]
    instruction: Annotated[str, Field(min_length=1, max_length=2000)]


class RecipeNutrition(Contract):
    """User-supplied only. Absent values render as unknown and are never
    derived from a tag or a dish name, per product doc section 5.3."""

    calories: Number | None = None
    proteinG: Number | None = None
    carbsG: Number | None = None
    fatG: Number | None = None
    fiberG: Number | None = None
    source: Literal["user", "imported", "unknown"] = "unknown"


class RecipeRating(Contract):
    recipeId: Identifier
    accountId: Identifier
    stars: int = Field(ge=1, le=5)


class Recipe(Contract):
    id: Identifier
    name: Identifier
    type: FoodType
    mealTypes: list[Slot]
    tags: list[str]
    servings: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    activeMinutes: Number
    elapsedMinutes: Number
    ingredients: list[Ingredient]
    steps: list[str]
    liked: bool
    source: str
    incomplete: bool = False
    allergens: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    # Frame 36:1030.
    nameEn: str | None = Field(default=None, max_length=200)
    cuisine: str | None = Field(default=None, max_length=60)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    heroImageUrl: str | None = Field(default=None, max_length=2000)
    nutrition: RecipeNutrition | None = None
    reheat: list[ReheatInstruction] = Field(default_factory=list)
    stepDetails: list[StepDetail] = Field(default_factory=list)

    @field_validator("heroImageUrl")
    @classmethod
    def safe_image(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Hero image must be an HTTP or HTTPS link without credentials")
        return value.strip()

    @model_validator(mode="after")
    def check_time(self) -> Self:
        if self.elapsedMinutes < self.activeMinutes:
            raise ValueError("elapsedMinutes cannot be less than activeMinutes")
        indexes = [detail.index for detail in self.stepDetails]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Duplicate step detail index")
        if any(index >= len(self.steps) for index in indexes):
            raise ValueError("Step detail refers to a step this recipe does not have")
        methods = [entry.method for entry in self.reheat]
        if len(methods) != len(set(methods)):
            raise ValueError("Duplicate reheating method")
        return self


class InventoryItem(Contract):
    id: Identifier
    name: Identifier
    type: FoodType
    portions: Number
    location: str
    prepared: bool
    addedOn: str
    recipeId: Identifier | None = None
    priority: bool
    # Frame 110:5. Absent values stay absent: the card shows the freshness and
    # weight it was told, never a guess derived from a name or a category.
    expiresOn: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    portionGrams: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    # Shared with every other batch of the same food, which is the point of a
    # single food record: renaming or re-iconing it updates each surface at once.
    emoji: str | None = Field(default=None, max_length=16)
    nameEn: str | None = Field(default=None, max_length=200)

    @field_validator("addedOn")
    @classmethod
    def date_valid(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("addedOn must be YYYY-MM-DD")
        return value

    @field_validator("expiresOn")
    @classmethod
    def expiry_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("expiresOn must be YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def expiry_after_storage(self) -> Self:
        if self.expiresOn and date.fromisoformat(self.expiresOn) < date.fromisoformat(self.addedOn):
            raise ValueError("expiresOn cannot precede addedOn")
        return self


class MealComponent(Contract):
    id: Identifier
    name: Identifier
    type: FoodType
    portions: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    recipeId: Identifier | None = None
    inventoryId: Identifier | None = None
    prepId: Identifier | None = None


class Meal(Contract):
    id: Identifier
    day: str
    slot: Slot
    # Step 1 of frame 47:9. False is "we deliberately do not cook this slot",
    # which is different from planned-and-then-skipped: an excluded slot never
    # enters the time budget, the supply check or the repetition rule.
    included: bool = True
    components: list[MealComponent] = Field(min_length=1)
    activeMinutes: Number
    elapsedMinutes: Number
    steps: list[str]
    status: Status
    liked: bool
    locked: bool


class PrepInput(Contract):
    inventoryId: Identifier
    portions: Number


class PrepTask(Contract):
    id: Identifier
    name: Identifier
    type: Literal["Protein", "Carbs", "Vegetables", "Other", "Baking"]
    recipeId: Identifier | None = None
    plannedPortions: Number
    actualPortions: Number
    activeMinutes: Number
    elapsedMinutes: Number
    steps: list[str]
    status: Status
    liked: bool
    outputInventoryId: Identifier | None = None
    inputs: list[PrepInput]
    equipment: list[str]
    dependencies: list[str]


class ChatMessage(Contract):
    id: Identifier
    role: Literal["user", "assistant"]
    text: str
    mealIds: list[str] = Field(default_factory=list)


class MealStylePreset(Contract):
    """The "Meal Style Presets" checklist on frame 47:9."""

    key: Identifier
    label: Annotated[str, Field(min_length=1, max_length=120)]
    emoji: str | None = Field(default=None, max_length=16)
    tint: str | None = Field(default=None, max_length=16)
    enabled: bool = True


# The checklist frame 47:9 ships with. It is the default, not a fixed list:
# `preset.save` edits it and a household can disable entries it never uses.
DEFAULT_MEAL_STYLE_PRESETS: tuple[tuple[str, str, str, str], ...] = (
    ("home_cooked", "Home-cooked priority", "\U0001f3e0", "#ebf9ee"),
    ("light_healthy", "Light & healthy", "\U0001f957", "#fffdf9"),
    ("meal_prep", "Meal prep friendly", "\U0001f371", "#ebf3f9"),
    ("baby_friendly", "Baby-friendly meals", "\U0001f476", "#fffdf9"),
    ("quick_30", "Quick meals (<30min)", "\u23f1\ufe0f", "#fffdf9"),
    ("fridge_first", "Use fridge items first", "\U0001f9ca", "#ebf9ee"),
)


def default_meal_style_presets() -> list[MealStylePreset]:
    return [
        MealStylePreset(key=key, label=label, emoji=emoji, tint=tint, enabled=True)
        for key, label, emoji, tint in DEFAULT_MEAL_STYLE_PRESETS
    ]


class Guidance(Contract):
    id: Identifier
    title: str
    content: str
    enabled: bool
    version: int = Field(ge=1)


class KnowledgeDocument(Contract):
    id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    content: Annotated[str, Field(min_length=1, max_length=100000)]
    category: Annotated[str, Field(min_length=1, max_length=100)] = "Nutrition"
    sourceUrl: str | None = Field(default=None, max_length=2000)
    enabled: bool = True
    version: int = Field(default=1, ge=1)
    updatedAt: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("title", "content", "category")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Document title, content and category cannot be blank")
        return value.strip()

    @field_validator("sourceUrl")
    @classmethod
    def safe_source(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Source URL must be an HTTP or HTTPS link without credentials")
        return value.strip()

    @field_validator("updatedAt")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("updatedAt must include its timezone")
        return value


class ShoppingRequirement(Contract):
    name: Identifier
    unit: Identifier
    group: str
    required: Number
    inStock: Number
    toBuy: Number
    dishes: list[str]

    @model_validator(mode="after")
    def quantities_agree(self) -> "ShoppingRequirement":
        if self.inStock > self.required or abs(self.required - self.inStock - self.toBuy) > 0.01:
            raise ValueError("Shopping quantities must satisfy required - inStock = toBuy")
        return self


class FulfillmentSnapshot(Contract):
    stale: bool = False
    shopping: list[ShoppingRequirement]
    warnings: list[str]
    generatedAt: str
    source: Literal["ai"]
    recipeHashes: dict[str, str] = Field(default_factory=dict)
    batchRecipes: list[str] = Field(default_factory=list)
    prepNotes: dict[str, str] = Field(default_factory=dict)


class RecurringMeal(Contract):
    weekday: int = Field(ge=0, le=6)
    slot: Slot
    meal: Meal
    prep: list[PrepTask] = Field(default_factory=list)


class WeeklyPlan(Contract):
    id: Identifier
    weekStart: str
    status: Literal["draft", "confirmed"]
    version: int = Field(ge=1)
    basePlanId: Identifier | None = None
    baseVersion: int | None = Field(default=None, ge=1)
    prompt: str
    meals: list[Meal]
    prep: list[PrepTask]
    chat: list[ChatMessage]
    # Preset keys this week selected, from the household catalog.
    presets: list[str] = Field(default_factory=list)
    fulfillment: FulfillmentSnapshot | None = None
    shoppingChecked: list[str] = Field(default_factory=list, max_length=2000)
    guidanceSnapshot: list[Guidance] = Field(default_factory=list)
    knowledgeSnapshot: list[KnowledgeDocument] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        start = date.fromisoformat(self.weekStart)
        if start.weekday() != 0:
            raise ValueError("weekStart must be Monday")
        slots = set()
        for meal in self.meals:
            if not 0 <= (date.fromisoformat(meal.day) - start).days < 7:
                raise ValueError("Meal date is outside this week")
            if (meal.day, meal.slot) in slots:
                raise ValueError("Duplicate meal slot")
            slots.add((meal.day, meal.slot))
            unique(meal.components)
        unique(self.meals)
        unique(self.prep)
        unique(self.chat)
        return self


class KitchenSettings(Contract):
    recurringMeals: list[RecurringMeal] = Field(default_factory=list, max_length=21)

    @field_validator("recurringMeals")
    @classmethod
    def unique_locks(cls, value: list[RecurringMeal]) -> list[RecurringMeal]:
        if len({(r.weekday, r.slot) for r in value}) != len(value):
            raise ValueError("Duplicate recurring meal slot")
        return value

    people: int = Field(default=3, ge=1, le=100)
    childAge: Number = 0
    allergies: list[str] = Field(default_factory=list)
    timezone: str = "America/Los_Angeles"
    generateTime: str = "17:00"
    prepDay: int = Field(default=6, ge=0, le=6)
    maxPrepMinutes: Number = 240
    maxDailyActiveMinutes: Number = 30
    newRecipesPerWeek: int = Field(default=2, ge=0, le=21)
    recipeRepeatGapDays: int = Field(default=1, ge=1, le=7)
    guidance: list[Guidance] = Field(default_factory=list)
    analysisMetrics: list[AnalysisMetric] = Field(default_factory=lambda: list(ANALYSIS_METRICS))
    # Tags leading the Recipe Book filters, in pin order; a meal is its slot.
    # Absent until chosen, which means DEFAULT_PINNED_TAGS.
    pinnedTags: list[TagName] | None = Field(default=None, max_length=200)

    @field_validator("pinnedTags")
    @classmethod
    def _unique_pins(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(dict.fromkeys(value))

    @field_validator("analysisMetrics")
    @classmethod
    def _catalog_order(cls, value: list[AnalysisMetric]) -> list[AnalysisMetric]:
        """One entry per metric, in catalog order, whatever order was sent."""
        return [metric for metric in ANALYSIS_METRICS if metric in value]

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("generateTime")
    @classmethod
    def time_valid(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("generateTime must be HH:mm")
        return value


class Delta(Contract):
    inventoryId: Identifier
    amount: float = Field(allow_inf_nan=False)


class AuditEntry(Contract):
    id: Identifier
    kind: str
    message: str
    at: str
    actorId: str | None = None
    operationId: str | None = None
    deltas: list[Delta] = Field(default_factory=list)
    undo: dict[str, Any] | None = None
    undone: bool = False
    planId: str | None = None
    entityId: str | None = None
    componentId: str | None = None


class PlanningWorkflow(Contract):
    planId: Identifier | None = None
    step: Literal["preferences", "adjust", "confirmed", "shopping"]
    focus: Literal["shopping", "prep"] = "shopping"


class WeeklyPrompt(Contract):
    weekStart: str
    prompt: str = Field(max_length=12000)
    workflow: PlanningWorkflow | None = None

    @field_validator("weekStart")
    @classmethod
    def monday_valid(cls, value: str) -> str:
        day = date.fromisoformat(value)
        if day.isoformat() != value or day.weekday() != 0:
            raise ValueError("weekStart must be YYYY-MM-DD Monday")
        return value


class Workspace(Contract):
    revision: int = Field(default=0, ge=0)
    recipes: list[Recipe] = Field(default_factory=list)
    knowledgeDocuments: list[KnowledgeDocument] = Field(default_factory=list)
    inventory: list[InventoryItem] = Field(default_factory=list)
    plans: list[WeeklyPlan] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Absent means "never configured", so the household starts from the
    # shipped checklist rather than an empty one.
    recipeRatings: list[RecipeRating] = Field(default_factory=list)
    mealStylePresets: list[MealStylePreset] = Field(default_factory=default_meal_style_presets)
    weeklyPrompts: list[WeeklyPrompt] = Field(default_factory=list)
    settings: KitchenSettings = Field(default_factory=KitchenSettings)
    audit: list[AuditEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        collections: tuple[Iterable[Identified], ...] = (
            self.recipes,
            self.knowledgeDocuments,
            self.inventory,
            self.plans,
            self.audit,
            self.settings.guidance,
        )
        for values in collections:
            unique(values)
        weeks = [entry.weekStart for entry in self.weeklyPrompts]
        if len(weeks) != len(set(weeks)):
            raise ValueError("Duplicate weekly prompts")
        return self


class KitchenCommand(Contract):
    type: Identifier
    payload: dict[str, Any]
    expectedRevision: int = Field(ge=0)
    operationId: Identifier


class Identified(Protocol):
    @property
    def id(self) -> str: ...


def unique(items: Iterable[Identified]) -> None:
    identifiers = [item.id for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate identifiers")
