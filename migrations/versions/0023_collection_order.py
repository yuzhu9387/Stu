"""Give the ordered collections their own position.

Recipes, fridge batches and plans are ordered arrays in the aggregate and the
UI renders them in that order. Rows written in a single loop share a
`created_at` to the microsecond, so ordering by timestamp falls back to a random
UUID and the list silently reshuffles. Tags and audit entries already carry a
position for the same reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_collection_order"
down_revision: str | None = "0022_allergy_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("kitchen_recipes", "inventory_batches", "weekly_plans")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table, sa.Column("position", sa.Integer(), nullable=False, server_default="0")
        )
        op.alter_column(table, "position", server_default=None)


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "position")
