"""Create durable Lark event receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_lark_event_receipts"
down_revision: str | None = "0001_identity_and_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lark_event_receipts",
        sa.Column("event_id", sa.String(128), primary_key=True, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("lark_event_receipts")
