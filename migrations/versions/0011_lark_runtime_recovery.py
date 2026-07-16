"""Add Lark event, run, and delivery recovery leases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_lark_runtime_recovery"
down_revision: str | None = "0010_durable_action_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))

    with op.batch_alter_table("lark_event_receipts") as batch_op:
        batch_op.add_column(sa.Column("fingerprint_hash", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "processing_status", sa.String(16), nullable=False, server_default="accepted"
            )
        )
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("outcome", sa.String(32)))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
    receipts = sa.table(
        "lark_event_receipts",
        sa.column("fingerprint_hash", sa.String(64)),
        sa.column("outcome", sa.String(32)),
    )
    op.get_bind().execute(
        sa.update(receipts).values(fingerprint_hash="0" * 64, outcome="legacy")
    )
    with op.batch_alter_table("lark_event_receipts") as batch_op:
        batch_op.alter_column(
            "fingerprint_hash", existing_type=sa.String(64), nullable=False
        )
        batch_op.create_check_constraint(
            "ck_lark_event_processing_status",
            "processing_status IN ('processing', 'accepted')",
        )

    op.create_table(
        "lark_delivery_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "outbox_event_id",
            sa.Uuid(),
            sa.ForeignKey("outbox_events.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'delivered', 'failed')",
            name="ck_lark_delivery_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("lark_delivery_receipts")
    with op.batch_alter_table("lark_event_receipts") as batch_op:
        batch_op.drop_constraint("ck_lark_event_processing_status", type_="check")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("outcome")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("processing_status")
        batch_op.drop_column("fingerprint_hash")
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("attempt_count")
