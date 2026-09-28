"""The child's birthday replaces a stored age, which is stale the day after it is written."""

import sqlalchemy as sa
from alembic import op

revision = "0032_child_birthday"
down_revision = "0031_mcp_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL means no birthday on record, which the planner reads as unknown.
    op.add_column(
        "household_kitchen_settings", sa.Column("child_birthday", sa.Date(), nullable=True)
    )
    # Whatever age was last typed in dates a birthday, so no household loses what
    # it had told us. A zero age meant unknown and stays unknown.
    op.execute(
        """
        UPDATE household_kitchen_settings
        SET child_birthday = (CURRENT_DATE - (child_age_months || ' months')::interval)::date
        WHERE child_age_months > 0
        """
    )
    op.drop_column("household_kitchen_settings", "child_age_months")


def downgrade() -> None:
    op.add_column(
        "household_kitchen_settings",
        sa.Column("child_age_months", sa.Numeric(6, 2), nullable=False, server_default="0"),
    )
    # Back to an age frozen at the moment of the downgrade.
    op.execute(
        """
        UPDATE household_kitchen_settings
        SET child_age_months = GREATEST(
            0,
            (DATE_PART('year', CURRENT_DATE) - DATE_PART('year', child_birthday)) * 12
            + DATE_PART('month', CURRENT_DATE) - DATE_PART('month', child_birthday)
            - CASE WHEN DATE_PART('day', CURRENT_DATE) < DATE_PART('day', child_birthday)
                   THEN 1 ELSE 0 END
        )
        WHERE child_birthday IS NOT NULL
        """
    )
    op.drop_column("household_kitchen_settings", "child_birthday")
