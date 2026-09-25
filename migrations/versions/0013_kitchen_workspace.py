"""Add validated kitchen aggregate and idempotent operation receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_kitchen_workspace"
down_revision: str | None = "0012_workspace_crud"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kitchen_workspaces",
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
    )
    op.create_table(
        "kitchen_operation_receipts",
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("operation_id", sa.String(200), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("kitchen_operation_receipts")
    op.drop_table("kitchen_workspaces")
