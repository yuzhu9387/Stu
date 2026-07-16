"""Recipe import persistence models."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.infrastructure.db.base import Base


class RawInputStatus(StrEnum):
    RECEIVED = "received"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"


class RawInput(Base):
    __tablename__ = "raw_inputs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[RawInputStatus] = mapped_column(
        Enum(RawInputStatus, native_enum=False), default=RawInputStatus.RECEIVED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="family")
    active_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class RecipeVersion(Base):
    __tablename__ = "recipe_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_recipe_ingredient_position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipe_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit: Mapped[str | None] = mapped_column(String(64))


class RecipeStep(Base):
    __tablename__ = "recipe_steps"
    __table_args__ = (UniqueConstraint("version_id", "number", name="uq_recipe_step_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipe_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    number: Mapped[int]
    text: Mapped[str] = mapped_column(Text, nullable=False)


class RecipeSource(Base):
    __tablename__ = "recipe_sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    raw_input_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("raw_inputs.id", ondelete="SET NULL")
    )
    source_url: Mapped[str | None] = mapped_column(Text)


class RecipeTag(Base):
    __tablename__ = "recipe_tags"
    __table_args__ = (UniqueConstraint("recipe_id", "name", name="uq_recipe_tag_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class RecipeEmbedding(Base):
    __tablename__ = "recipe_embeddings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    vector_json: Mapped[str] = mapped_column(Text, nullable=False)


class MediaObject(Base):
    __tablename__ = "media_objects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    raw_input_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_inputs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
