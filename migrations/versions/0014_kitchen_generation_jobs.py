"""Durable timezone-aware kitchen generation claims."""

import sqlalchemy as sa
from alembic import op

revision = "0014_kitchen_generation_jobs"
down_revision = "0013_kitchen_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "kitchen_generation_jobs",
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("week_start", sa.String(10), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
    )


def downgrade():
    op.drop_table("kitchen_generation_jobs")
