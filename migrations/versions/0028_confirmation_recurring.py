"""AI fulfillment snapshots and household recurring meals."""

import sqlalchemy as sa
from alembic import op

revision = "0028_confirmation_recurring"
down_revision = "0027_planning_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("weekly_plans", sa.Column("fulfillment", sa.JSON(), nullable=True))
    op.add_column(
        "household_kitchen_settings",
        sa.Column("recurring_meals", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("household_kitchen_settings", "recurring_meals")
    op.drop_column("weekly_plans", "fulfillment")
