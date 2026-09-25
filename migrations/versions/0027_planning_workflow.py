"""Persist the weekly journey and plan-scoped shopping checklist."""

import sqlalchemy as sa
from alembic import op

revision = "0027_planning_workflow"
down_revision = "0026_kitchen_ai_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("weekly_prompts", sa.Column("workflow", sa.JSON(), nullable=True))
    op.add_column(
        "weekly_plans",
        sa.Column("shopping_checked", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("weekly_plans", "shopping_checked")
    op.drop_column("weekly_prompts", "workflow")
