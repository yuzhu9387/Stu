"""Add durable suggested-action execution outcomes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_suggested_action_execution"
down_revision: str | None = "0008_live_read_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("suggested_actions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "execution_status",
                sa.String(16),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("result_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(64), nullable=True))
        batch_op.create_check_constraint(
            "ck_suggested_actions_execution_status",
            "execution_status IN ('pending', 'executing', 'succeeded', 'failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("suggested_actions") as batch_op:
        batch_op.drop_constraint("ck_suggested_actions_execution_status", type_="check")
        batch_op.drop_column("error_code")
        batch_op.drop_column("result_json")
        batch_op.drop_column("execution_status")
