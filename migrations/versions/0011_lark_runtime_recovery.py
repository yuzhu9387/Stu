"""Add Lark event, run, and delivery recovery leases."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

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
    agent_runs = sa.table(
        "agent_runs",
        sa.column("status", sa.String(32)),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.get_bind().execute(
        sa.update(agent_runs)
        .where(agent_runs.c.status == "running")
        .values(lease_expires_at=datetime(1970, 1, 1, tzinfo=UTC))
    )

    with op.batch_alter_table("lark_event_receipts") as batch_op:
        batch_op.add_column(sa.Column("fingerprint_hash", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column("processing_status", sa.String(16), nullable=False, server_default="accepted")
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
    op.get_bind().execute(sa.update(receipts).values(fingerprint_hash="0" * 64, outcome="legacy"))
    with op.batch_alter_table("lark_event_receipts") as batch_op:
        batch_op.alter_column("fingerprint_hash", existing_type=sa.String(64), nullable=False)
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
    outbox_events = sa.table(
        "outbox_events",
        sa.column("id", sa.Uuid()),
        sa.column("topic", sa.String(160)),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )
    delivery_receipts = sa.table(
        "lark_delivery_receipts",
        sa.column("id", sa.Uuid()),
        sa.column("outbox_event_id", sa.Uuid()),
        sa.column("dedupe_key", sa.String(200)),
        sa.column("status", sa.String(16)),
        sa.column("attempt_count", sa.Integer()),
    )
    legacy_lark_events = tuple(
        op.get_bind()
        .execute(sa.select(outbox_events.c.id).where(outbox_events.c.topic.like("lark.%")))
        .scalars()
    )
    if legacy_lark_events:
        op.get_bind().execute(
            sa.insert(delivery_receipts),
            [
                {
                    "id": uuid4(),
                    "outbox_event_id": event_id,
                    "dedupe_key": f"legacy-outbox:{event_id}",
                    "status": "pending",
                    "attempt_count": 0,
                }
                for event_id in legacy_lark_events
            ],
        )
        op.get_bind().execute(
            sa.update(outbox_events)
            .where(outbox_events.c.id.in_(legacy_lark_events))
            .values(published_at=None)
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
