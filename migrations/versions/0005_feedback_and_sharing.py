"""Create feedback memory and private share snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_feedback_and_sharing"
down_revision: str | None = "0004_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_feedback_events_household_id", "feedback_events", ["household_id"])
    op.create_index("ix_feedback_events_recipe_id", "feedback_events", ["recipe_id"])
    op.create_table(
        "recipe_version_deltas",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("recipe_versions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("instruction", sa.Text(), nullable=False),
    )
    op.create_table(
        "recipe_ratings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.CheckConstraint("value >= 1 AND value <= 5", name="ck_rating_range"),
    )
    op.create_index("ix_recipe_ratings_household_id", "recipe_ratings", ["household_id"])
    op.create_index("ix_recipe_ratings_recipe_id", "recipe_ratings", ["recipe_id"])
    op.create_table(
        "share_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_share_snapshots_token_hash", "share_snapshots", ["token_hash"])


def downgrade() -> None:
    op.drop_table("share_snapshots")
    op.drop_table("recipe_ratings")
    op.drop_table("recipe_version_deltas")
    op.drop_table("feedback_events")
