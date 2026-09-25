"""Hold the batch id a planned prep task reserves.

A prep task names the inventory batch it will produce while still planned, so
the reservation cannot be a foreign key: the row does not exist until the task
completes. The key travels alongside, and the foreign key fills in afterwards.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_prep_output_key"
down_revision: str | None = "0020_snapshot_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prep_tasks", sa.Column("output_batch_key", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("prep_tasks", "output_batch_key")
