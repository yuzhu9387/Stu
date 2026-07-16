"""Immutable planning and shopping contracts."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IngredientAmount(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    unit: str = Field(min_length=1)


class PlanItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    day: date
    slot: str = Field(min_length=1)
    recipe_id: UUID
    recipe_name: str = Field(min_length=1)
    reason_codes: tuple[str, ...]
    ingredients: tuple[IngredientAmount, ...] = ()


class PlanSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: date
    slot: str = Field(min_length=1)


class MealPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_account_id: UUID
    household_id: UUID
    week_start: date
    version: int = Field(ge=1)
    items: tuple[PlanItem, ...]


class ShoppingEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    quantity: Decimal
    unit: str
    checked: bool = False


class ShoppingListDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: tuple[ShoppingEntry, ...]

    def quantity_for(self, name: str, unit: str) -> Decimal:
        canonical_name = name.strip().casefold()
        canonical_unit = unit.strip().casefold()
        for entry in self.entries:
            if entry.name == canonical_name and entry.unit == canonical_unit:
                return entry.quantity
        return Decimal(0)

    def entries_for(self, name: str) -> int:
        canonical_name = name.strip().casefold()
        return sum(entry.name == canonical_name for entry in self.entries)
