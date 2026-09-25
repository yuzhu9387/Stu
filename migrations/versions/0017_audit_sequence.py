"""Record the append order of audit entries.

Undo walks forward from an entry to check for dependent activity, so the order
is semantic. Two commands can share a timestamp, so `at` alone cannot recover it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_audit_sequence"
down_revision: str | None = "0016_kitchen_backfill_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kitchen_audit_entries",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("kitchen_audit_entries", "sequence", server_default=None)


def downgrade() -> None:
    op.drop_column("kitchen_audit_entries", "sequence")
