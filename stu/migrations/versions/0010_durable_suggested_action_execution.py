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

    _recover_and_scrub_legacy_actions()

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
    _normalize_actions_for_downgrade()
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


def _recover_and_scrub_legacy_actions() -> None:
    actions = sa.table(
        "suggested_actions",
        sa.column("id", sa.Uuid()),
        sa.column("account_id", sa.Uuid()),
        sa.column("action_type", sa.String()),
        sa.column("execution_status", sa.String()),
        sa.column("result_json", sa.Text()),
        sa.column("error_code", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.column("consumed_at", sa.DateTime(timezone=True)),
        sa.column("consumed_by_account_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    connection.execute(
        sa.update(actions)
        .where(actions.c.action_type == "create_share", actions.c.result_json.is_not(None))
        .values(
            execution_status="failed",
            result_json=None,
            error_code="legacy_share_result_scrubbed",
            lease_expires_at=None,
        )
    )
    connection.execute(
        sa.update(actions)
        .where(actions.c.execution_status == "executing")
        .values(
            execution_status="failed",
            lease_expires_at=None,
            result_json=None,
            error_code="legacy_execution_unrecoverable",
            consumed_at=sa.func.coalesce(actions.c.consumed_at, actions.c.created_at),
            consumed_by_account_id=sa.func.coalesce(
                actions.c.consumed_by_account_id, actions.c.account_id
            ),
        )
    )


def _normalize_actions_for_downgrade() -> None:
    actions = sa.table(
        "suggested_actions",
        sa.column("action_type", sa.String()),
        sa.column("execution_status", sa.String()),
        sa.column("result_json", sa.Text()),
        sa.column("error_code", sa.String()),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    connection.execute(
        sa.update(actions)
        .where(actions.c.action_type == "create_share", actions.c.result_json.is_not(None))
        .values(
            execution_status="failed",
            result_json=None,
            error_code="legacy_share_result_scrubbed",
            lease_expires_at=None,
        )
    )
    connection.execute(
        sa.update(actions)
        .where(actions.c.execution_status.in_(("queued", "executing")))
        .values(
            execution_status="failed",
            result_json=None,
            error_code="downgrade_incomplete_action",
            lease_expires_at=None,
        )
    )
