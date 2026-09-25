"""Normalised kitchen tables derived from the Figma workspace frames.

One row per fact. Food, equipment and tags are shared vocabulary so a recipe
ingredient, a fridge batch and a preference all reference the same record
instead of repeating a string. Stock balances come from an append-only ledger,
so history and balance cannot disagree.

Design: docs/superpowers/specs/2026-09-20-relational-schema.md
The JSON aggregate in models.py stays in place until the staged cutover
described there is complete.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class FoodCategory(StrEnum):
    PROTEIN = "protein"
    CARBS = "carbs"
    VEGETABLES = "vegetables"
    DAIRY = "dairy"
    OTHER = "other"


class StorageLocation(StrEnum):
    FRIDGE = "fridge"
    FREEZER = "freezer"
    PANTRY = "pantry"


class MealSlot(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"


class ExecutionStatus(StrEnum):
    PLANNED = "planned"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PrepCategory(StrEnum):
    PROTEIN = "protein"
    CARBS = "carbs"
    VEGETABLES = "vegetables"
    BAKING = "baking"
    OTHER = "other"


class ReheatMethod(StrEnum):
    MICROWAVE = "microwave"
    STEAMER = "steamer"
    PAN = "pan"
    OVEN = "oven"
    OTHER = "other"


class NutritionSource(StrEnum):
    USER = "user"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


class LedgerReason(StrEnum):
    PREP_OUTPUT = "prep_output"
    PREP_INPUT = "prep_input"
    MEAL_CONSUMPTION = "meal_consumption"
    LEFTOVER_RETURN = "leftover_return"
    MANUAL_ADJUST = "manual_adjust"
    UNDO_REVERSAL = "undo_reversal"


class MealEventKind(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    LIKED = "liked"
    UNLIKED = "unliked"
    REOPENED = "reopened"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


def _household() -> Mapped[UUID]:
    return mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )


# --------------------------------------------------------------------------
# Shared vocabulary
# --------------------------------------------------------------------------


class FoodItem(Base):
    """Canonical food, referenced by recipes, fridge batches and preferences."""

    __tablename__ = "food_items"
    __table_args__ = (UniqueConstraint("household_id", "name", name="uq_food_item_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[FoodCategory] = mapped_column(String(16), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    # Null means unknown. Never inferred from a name.
    default_portion_grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("household_id", "name", name="uq_equipment_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Tag(Base):
    __tablename__ = "kitchen_tags"
    __table_args__ = (UniqueConstraint("household_id", "name", name="uq_kitchen_tag_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # False when only a recipe introduced it, so the catalog round-trips exactly.
    listed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The catalog renders as an ordered chip row; tag.save appends.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# --------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------


class KitchenRecipe(Base):
    """Named apart from the legacy `recipes` table, which keeps its own routes."""

    __tablename__ = "kitchen_recipes"
    __table_args__ = (
        UniqueConstraint("household_id", "legacy_id", name="uq_kitchen_recipe_legacy"),
        CheckConstraint("servings > 0", name="ck_recipe_servings_positive"),
        CheckConstraint("elapsed_minutes >= active_minutes", name="ck_recipe_elapsed_ge_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    # Transport id carried over from the JSON aggregate; frontend URLs use it.
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    # The aggregate keeps this collection as an ordered array and the UI
    # renders it in that order. Row timestamps tie when a batch is written
    # in one loop, so the order needs its own column.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[FoodCategory] = mapped_column(
        String(16), nullable=False, default=FoodCategory.OTHER
    )
    cuisine: Mapped[str | None] = mapped_column(String(60))
    hero_media_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("media_objects.id", ondelete="SET NULL")
    )
    # A linked photo. Uploads are not wired yet, so this carries a URL the user
    # pasted; hero_media_id takes over once an upload endpoint exists.
    hero_image_url: Mapped[str | None] = mapped_column(String(2000))
    servings: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    active_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    elapsed_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    difficulty: Mapped[Difficulty | None] = mapped_column(String(16))
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient_items"
    __table_args__ = (
        UniqueConstraint("recipe_id", "position", name="uq_kitchen_recipe_ingredient_position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    food_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("food_items.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    # 肉类 / 辅料 / 调味糖色 / 调味料 grouping from frame 36:1030.
    group_label: Mapped[str | None] = mapped_column(String(60))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class RecipeStep(Base):
    __tablename__ = "kitchen_recipe_steps"
    __table_args__ = (UniqueConstraint("recipe_id", "position", name="uq_recipe_step_position"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    title_en: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Split so the scheduler keeps unattended tails out of hands-on time.
    active_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    wait_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))


class RecipeReheatInstruction(Base):
    __tablename__ = "recipe_reheat_instructions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    method: Mapped[ReheatMethod] = mapped_column(String(16), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RecipeNutrition(Base):
    """User-supplied only. Absent rows render as unknown; nothing is derived."""

    __tablename__ = "recipe_nutrition"

    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), primary_key=True
    )
    calories: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    source: Mapped[NutritionSource] = mapped_column(
        String(16), nullable=False, default=NutritionSource.UNKNOWN
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class RecipeTagLink(Base):
    __tablename__ = "kitchen_recipe_tags"

    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_tags.id", ondelete="CASCADE"), primary_key=True
    )


class RecipeEquipmentLink(Base):
    __tablename__ = "recipe_equipment"

    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True
    )


class RecipeMealSlotLink(Base):
    __tablename__ = "recipe_meal_slots"

    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), primary_key=True
    )
    slot: Mapped[MealSlot] = mapped_column(String(16), primary_key=True)


class KitchenRecipeRating(Base):
    """`⭐ 4.9 (42 ratings)` is avg/count over these rows, never a stored total."""

    __tablename__ = "kitchen_recipe_ratings"
    __table_args__ = (
        UniqueConstraint("recipe_id", "account_id", name="uq_kitchen_rating_account"),
        CheckConstraint("stars BETWEEN 1 AND 5", name="ck_kitchen_rating_stars"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------------------
# Fridge
# --------------------------------------------------------------------------


class InventoryBatch(Base):
    """One physical batch. Portions are the sum of its ledger entries."""

    __tablename__ = "inventory_batches"
    __table_args__ = (
        UniqueConstraint("household_id", "legacy_id", name="uq_inventory_batch_legacy"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    food_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("food_items.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    recipe_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="SET NULL"), index=True
    )
    portion_grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    location: Mapped[StorageLocation] = mapped_column(String(16), nullable=False)
    prepared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stored_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class InventoryLedgerEntry(Base):
    """Append-only stock movement. Undo writes a compensating row."""

    __tablename__ = "inventory_ledger_entries"
    __table_args__ = (Index("ix_inventory_ledger_batch_time", "batch_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    batch_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_batches.id", ondelete="CASCADE"), nullable=False
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    # Position within its audit entry; several rows share one timestamp.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[LedgerReason] = mapped_column(String(24), nullable=False)
    meal_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("meals.id", ondelete="SET NULL"))
    prep_task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="SET NULL")
    )
    audit_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("kitchen_audit_entries.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"
    __table_args__ = (
        Index("ix_weekly_plan_household_week", "household_id", "week_start"),
        UniqueConstraint("household_id", "legacy_id", name="uq_weekly_plan_legacy"),
        CheckConstraint("version >= 1", name="ck_weekly_plan_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_plan_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="SET NULL")
    )
    base_version: Mapped[int | None] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fulfillment: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    shopping_checked: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Meal(Base):
    """A slot exists whether or not it holds food, so step 1 of 47:9 can opt out."""

    __tablename__ = "meals"
    __table_args__ = (
        UniqueConstraint("plan_id", "day", "slot", name="uq_meal_plan_day_slot"),
        UniqueConstraint("plan_id", "legacy_id", name="uq_meal_legacy"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    day: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[MealSlot] = mapped_column(String(16), nullable=False)
    # False is "we deliberately do not cook this slot", distinct from skipped.
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        String(16), nullable=False, default=ExecutionStatus.PLANNED
    )
    liked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    elapsed_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MealComponent(Base):
    """Fresh cooking sets only recipe_id; an allocation names a batch or prep."""

    __tablename__ = "meal_components"
    __table_args__ = (
        CheckConstraint(
            "food_item_id IS NOT NULL OR recipe_id IS NOT NULL "
            "OR inventory_batch_id IS NOT NULL OR prep_task_id IS NOT NULL",
            name="ck_meal_component_reference",
        ),
        CheckConstraint("portions > 0", name="ck_meal_component_portions"),
        UniqueConstraint("meal_id", "legacy_id", name="uq_meal_component_legacy"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    portions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    food_item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("food_items.id", ondelete="SET NULL")
    )
    recipe_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="SET NULL")
    )
    inventory_batch_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_batches.id", ondelete="SET NULL")
    )
    prep_task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="SET NULL")
    )


class MealStep(Base):
    __tablename__ = "meal_steps"
    __table_args__ = (UniqueConstraint("meal_id", "position", name="uq_meal_step_position"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class MealEvent(Base):
    """Append-only execution history; times-cooked and undo both read it."""

    __tablename__ = "meal_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    meal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[MealEventKind] = mapped_column(String(16), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    audit_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("kitchen_audit_entries.id", ondelete="SET NULL")
    )


# --------------------------------------------------------------------------
# Prep
# --------------------------------------------------------------------------


class PrepTask(Base):
    __tablename__ = "prep_tasks"
    __table_args__ = (UniqueConstraint("plan_id", "legacy_id", name="uq_prep_task_legacy"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    recipe_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[PrepCategory] = mapped_column(String(16), nullable=False)
    planned_portions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    actual_portions: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    active_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    elapsed_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    status: Mapped[ExecutionStatus] = mapped_column(
        String(16), nullable=False, default=ExecutionStatus.PLANNED
    )
    liked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    output_batch_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_batches.id", ondelete="SET NULL")
    )
    # A planned task reserves the id of the batch it will produce, before that
    # batch exists, so the reservation cannot live in the foreign key.
    output_batch_key: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PrepTaskStep(Base):
    __tablename__ = "prep_task_steps"
    __table_args__ = (UniqueConstraint("prep_task_id", "position", name="uq_prep_step_position"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prep_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class PrepTaskInput(Base):
    __tablename__ = "prep_task_inputs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prep_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    inventory_batch_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_batches.id", ondelete="RESTRICT"), nullable=False
    )
    portions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class PrepTaskDependency(Base):
    __tablename__ = "prep_task_dependencies"
    __table_args__ = (
        CheckConstraint(
            "prep_task_id <> depends_on_prep_task_id", name="ck_prep_dependency_not_self"
        ),
    )

    prep_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_prep_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="CASCADE"), primary_key=True
    )


class PrepTaskEquipmentLink(Base):
    __tablename__ = "prep_task_equipment"

    prep_task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("prep_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True
    )


# --------------------------------------------------------------------------
# Planning inputs
# --------------------------------------------------------------------------


class MealStylePreset(Base):
    """The 47:9 "Meal Style Presets" catalog."""

    __tablename__ = "meal_style_presets"
    __table_args__ = (UniqueConstraint("household_id", "key", name="uq_meal_style_preset_key"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    tint: Mapped[str | None] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlanPreset(Base):
    __tablename__ = "plan_presets"

    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="CASCADE"), primary_key=True
    )
    preset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meal_style_presets.id", ondelete="CASCADE"), primary_key=True
    )


class WeeklyPrompt(Base):
    """Saved before a plan exists, so the Friday dispatcher can read it."""

    __tablename__ = "weekly_prompts"
    __table_args__ = (UniqueConstraint("household_id", "week_start", name="uq_weekly_prompt_week"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    workflow: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class PlanChatMessage(Base):
    __tablename__ = "plan_chat_messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[ChatRole] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlanChatReference(Base):
    """The `#Wed · Dinner` chips on frame 105:513."""

    __tablename__ = "plan_chat_references"

    message_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("plan_chat_messages.id", ondelete="CASCADE"), primary_key=True
    )
    meal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meals.id", ondelete="CASCADE"), primary_key=True
    )


# --------------------------------------------------------------------------
# Guidance and knowledge
# --------------------------------------------------------------------------


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("household_id", "legacy_id", name="uq_knowledge_document_legacy"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="Nutrition")
    source_url: Mapped[str | None] = mapped_column(String(2000))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_knowledge_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GuidanceRule(Base):
    __tablename__ = "guidance_rules"
    __table_args__ = (
        UniqueConstraint("household_id", "legacy_id", name="uq_guidance_rule_legacy"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GuidanceRuleVersion(Base):
    __tablename__ = "guidance_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_guidance_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    rule_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("guidance_rules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlanKnowledgeSnapshot(Base):
    """Pins a version row rather than copying text into the plan."""

    __tablename__ = "plan_knowledge_snapshots"

    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="CASCADE"), primary_key=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_document_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    # The number the plan pinned. Kept here so a preserved version row can take
    # any free slot without changing what the snapshot reports.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PlanGuidanceSnapshot(Base):
    __tablename__ = "plan_guidance_snapshots"

    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="CASCADE"), primary_key=True
    )
    guidance_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("guidance_rule_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


class KitchenAuditEntry(Base):
    __tablename__ = "kitchen_audit_entries"
    __table_args__ = (
        Index("ix_kitchen_audit_household_time", "household_id", "at"),
        UniqueConstraint("household_id", "legacy_id", name="uq_kitchen_audit_legacy"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    legacy_id: Mapped[str | None] = mapped_column(String(200))
    # Undo walks forward from an entry, so append order is semantic and cannot
    # be recovered from `at` alone once two commands share a timestamp.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    operation_id: Mapped[str | None] = mapped_column(String(200))
    plan_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("weekly_plans.id", ondelete="SET NULL")
    )
    entity_id: Mapped[str | None] = mapped_column(String(200))
    component_id: Mapped[str | None] = mapped_column(String(200))
    undo: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    undone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RecipeAllergen(Base):
    """Free text, because an allergen is not always a catalogued food."""

    __tablename__ = "recipe_allergens"
    __table_args__ = (UniqueConstraint("recipe_id", "label", name="uq_recipe_allergen"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)


class HouseholdKitchenSettings(Base):
    """Scheduler and planner inputs. The Settings screens are deferred, but the
    engine needs these values for Calendar, Plan, Prep and Fridge."""

    __tablename__ = "household_kitchen_settings"

    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    people: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    child_age_months: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    generate_time: Mapped[str] = mapped_column(String(5), nullable=False, default="17:00")
    prep_day: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    max_prep_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=240)
    max_daily_active_minutes: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=30
    )
    new_recipes_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    recurring_meals: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # Tags pinned to the front of the recipe filters; NULL until first chosen.
    pinned_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    recipe_repeat_gap_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class HouseholdAnalysisMetric(Base):
    """Whether the household's plan analysis looks at one catalogued metric.

    One row per metric once the household has saved a choice, each with its own
    on/off flag. Storing only the enabled ones would make "no rows" ambiguous —
    never chosen, or everything switched off — and the default is everything on.
    """

    __tablename__ = "household_analysis_metrics"
    __table_args__ = (
        UniqueConstraint("household_id", "metric", name="uq_household_analysis_metric"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class HouseholdAllergy(Base):
    """Household-wide restriction. food_item_id is set when it names a known food."""

    __tablename__ = "household_allergies"
    __table_args__ = (UniqueConstraint("household_id", "label", name="uq_household_allergy"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = _household()
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # Rendered as a joined list, so the author's order is user-visible.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    food_item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("food_items.id", ondelete="SET NULL")
    )
