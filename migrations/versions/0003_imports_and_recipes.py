"""Create raw imports and normalized recipe library."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_imports_and_recipes"
down_revision: str | None = "0002_lark_event_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    _create_import_tables()
    _create_recipe_tables()


def _create_import_tables() -> None:
    op.create_table(
        "raw_inputs",
        _id(),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("raw_text", sa.Text()),
        sa.Column("object_key", sa.String(512)),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("error", sa.Text()),
        _created_at(),
    )
    op.create_index("ix_raw_inputs_household_id", "raw_inputs", ["household_id"])
    op.create_table(
        "media_objects",
        _id(),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_type", sa.String(128), nullable=False),
    )
    op.create_index("ix_media_objects_household_id", "media_objects", ["household_id"])
    op.create_table(
        "import_jobs",
        _id(),
        sa.Column(
            "raw_input_id",
            sa.Uuid(),
            sa.ForeignKey("raw_inputs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.create_index("ix_import_jobs_raw_input_id", "import_jobs", ["raw_input_id"])


def _create_recipe_tables() -> None:
    op.create_table(
        "recipes",
        _id(),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("active_version_id", sa.Uuid()),
        _created_at(),
    )
    op.create_index("ix_recipes_household_id", "recipes", ["household_id"])
    op.create_table(
        "recipe_versions",
        _id(),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_version_id", sa.Uuid()),
        sa.Column("name", sa.String(300), nullable=False),
        _created_at(),
    )
    op.create_index("ix_recipe_versions_recipe_id", "recipe_versions", ["recipe_id"])
    op.create_table(
        "recipe_ingredients",
        _id(),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("recipe_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6)),
        sa.Column("unit", sa.String(64)),
        sa.UniqueConstraint("version_id", "position", name="uq_recipe_ingredient_position"),
    )
    op.create_index(
        "ix_recipe_ingredients_version_id", "recipe_ingredients", ["version_id"]
    )
    op.create_table(
        "recipe_steps",
        _id(),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("recipe_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.UniqueConstraint("version_id", "number", name="uq_recipe_step_number"),
    )
    op.create_index("ix_recipe_steps_version_id", "recipe_steps", ["version_id"])
    _create_recipe_metadata_tables()


def _create_recipe_metadata_tables() -> None:
    op.create_table(
        "recipe_sources",
        _id(),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raw_input_id",
            sa.Uuid(),
            sa.ForeignKey("raw_inputs.id", ondelete="SET NULL"),
        ),
        sa.Column("source_url", sa.Text()),
    )
    op.create_index("ix_recipe_sources_recipe_id", "recipe_sources", ["recipe_id"])
    op.create_table(
        "recipe_tags",
        _id(),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("recipe_id", "name", name="uq_recipe_tag_name"),
    )
    op.create_index("ix_recipe_tags_recipe_id", "recipe_tags", ["recipe_id"])
    op.create_table(
        "recipe_embeddings",
        _id(),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("vector_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_recipe_embeddings_recipe_id", "recipe_embeddings", ["recipe_id"])


def downgrade() -> None:
    for table in (
        "recipe_embeddings",
        "recipe_tags",
        "recipe_sources",
        "recipe_steps",
        "recipe_ingredients",
        "recipe_versions",
        "recipes",
        "import_jobs",
        "media_objects",
        "raw_inputs",
    ):
        op.drop_table(table)
