"""Which angles the household's plan analysis looks from.

A fixed catalog of metrics (weekend prep, daily cooking time, food-group
balance, repetition, fridge usage); the household switches each on or off in
Planning Guidance. One row per metric with its own flag, so an empty table for a
household unambiguously means "never chosen" and the default — all on — applies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_household_analysis_metrics"
down_revision: str | None = "0024_recipe_detail_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household_analysis_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "metric", name="uq_household_analysis_metric"),
    )
    op.create_index(
        op.f("ix_household_analysis_metrics_household_id"),
        "household_analysis_metrics",
        ["household_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_household_analysis_metrics_household_id"),
        table_name="household_analysis_metrics",
    )
    op.drop_table("household_analysis_metrics")
