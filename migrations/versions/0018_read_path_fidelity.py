"""Columns the relational read path needs to reproduce the transport exactly.

Found by diffing the rebuilt workspace against the JSON aggregate for a real
household: delta order inside an audit entry, the leftovers component, chat
message ids, and tags a recipe introduced without the catalog listing them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_read_path_fidelity"
down_revision: str | None = "0017_audit_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inventory_ledger_entries",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("inventory_ledger_entries", "sequence", server_default=None)
    op.add_column(
        "kitchen_audit_entries", sa.Column("component_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "plan_chat_messages", sa.Column("legacy_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "kitchen_tags",
        sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("kitchen_tags", "listed", server_default=None)


def downgrade() -> None:
    op.drop_column("kitchen_tags", "listed")
    op.drop_column("plan_chat_messages", "legacy_id")
    op.drop_column("kitchen_audit_entries", "component_id")
    op.drop_column("inventory_ledger_entries", "sequence")
