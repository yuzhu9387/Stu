"""Household aggregate and durable idempotency receipts."""

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class KitchenWorkspace(Base):
    __tablename__ = "kitchen_workspaces"
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class KitchenOperationReceipt(Base):
    __tablename__ = "kitchen_operation_receipts"
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    operation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
