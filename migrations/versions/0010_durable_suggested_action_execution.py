"""Add durable suggested-action queue leases and mutation receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_durable_action_execution"
down_revision: str | None = "0009_suggested_action_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("suggested_actions") as batch_op:
        batch_op.drop_constraint("ck_suggested_actions_execution_status", type_="check")
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch_op.create_check_constraint(
            "ck_suggested_actions_execution_status",
            "execution_status IN ('pending', 'queued', 'executing', 'succeeded', 'failed')",
        )

    op.create_table(
        "action_mutation_receipts",
        sa.Column(
            "action_id",
            sa.Uuid(),
            sa.ForeignKey("suggested_actions.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("share_snapshots") as batch_op:
        batch_op.add_column(sa.Column("source_action_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_share_snapshots_source_action_id_suggested_actions",
            "suggested_actions",
            ["source_action_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_share_snapshots_source_action_id", ["source_action_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("share_snapshots") as batch_op:
        batch_op.drop_constraint("uq_share_snapshots_source_action_id", type_="unique")
        batch_op.drop_constraint(
            "fk_share_snapshots_source_action_id_suggested_actions", type_="foreignkey"
        )
        batch_op.drop_column("source_action_id")
    op.drop_table("action_mutation_receipts")
    with op.batch_alter_table("suggested_actions") as batch_op:
        batch_op.drop_constraint("ck_suggested_actions_execution_status", type_="check")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("attempt_count")
        batch_op.create_check_constraint(
            "ck_suggested_actions_execution_status",
            "execution_status IN ('pending', 'executing', 'succeeded', 'failed')",
        )
