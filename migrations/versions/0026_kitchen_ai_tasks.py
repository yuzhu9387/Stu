"""Stu's AI work as stored tasks.

A chat turn or a week's draft runs on the server after the request that
started it returns; its outcome is kept here so a refresh or a page switch
picks it up instead of losing it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_kitchen_ai_tasks"
down_revision: str | None = "0025_household_analysis_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kitchen_ai_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("week_start", sa.String(length=10), nullable=False),
        sa.Column("plan_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolution", sa.String(length=16), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kitchen_ai_tasks_lookup",
        "kitchen_ai_tasks",
        ["household_id", "kind", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_kitchen_ai_tasks_lookup", table_name="kitchen_ai_tasks")
    op.drop_table("kitchen_ai_tasks")
