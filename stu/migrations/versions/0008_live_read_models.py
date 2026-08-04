"""Add live settings and authenticated share ownership read models."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_live_read_models"
down_revision: str | None = "0007_unified_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dietary_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "owner_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="family"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_account_id", "label", name="uq_dietary_preferences_owner_label"),
    )
    op.create_index("ix_dietary_preferences_household_id", "dietary_preferences", ["household_id"])
    with op.batch_alter_table("share_snapshots") as batch_op:
        batch_op.add_column(sa.Column("owner_account_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("household_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_share_snapshots_owner_account_id",
            "accounts",
            ["owner_account_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_share_snapshots_household_id",
            "households",
            ["household_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_share_snapshots_household_id", ["household_id"])


def downgrade() -> None:
    with op.batch_alter_table("share_snapshots") as batch_op:
        batch_op.drop_index("ix_share_snapshots_household_id")
        batch_op.drop_constraint("fk_share_snapshots_household_id", type_="foreignkey")
        batch_op.drop_constraint("fk_share_snapshots_owner_account_id", type_="foreignkey")
        batch_op.drop_column("household_id")
        batch_op.drop_column("owner_account_id")
    op.drop_table("dietary_preferences")
