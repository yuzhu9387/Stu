"""Feedback and rating persistence models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class FeedbackEventRecord(Base):
    __tablename__ = "feedback_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class RecipeVersionDeltaRecord(Base):
    __tablename__ = "recipe_version_deltas"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipe_versions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    instruction: Mapped[str] = mapped_column(Text, nullable=False)


class RatingRecord(Base):
    __tablename__ = "recipe_ratings"
    __table_args__ = (CheckConstraint("value >= 1 AND value <= 5", name="ck_rating_range"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
