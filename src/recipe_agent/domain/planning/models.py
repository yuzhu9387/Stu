"""Planning and shopping persistence models."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class MealPlanRecord(Base):
    __tablename__ = "meal_plans"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="family")
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PlanItemRecord(Base):
    __tablename__ = "meal_plan_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meal_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(32), nullable=False)
    recipe_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    recipe_name: Mapped[str] = mapped_column(String(300), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    ingredients_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class ShoppingListRecord(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("meal_plans.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ShoppingItemRecord(Base):
    __tablename__ = "shopping_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    shopping_list_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
