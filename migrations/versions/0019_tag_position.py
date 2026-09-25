"""Keep the tag catalog's order.

The Recipes screen renders tags as an ordered chip row and `tag.save` appends,
so insertion order is user-visible and cannot be recovered from a random UUID.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_tag_position"
down_revision: str | None = "0018_read_path_fidelity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kitchen_tags",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("kitchen_tags", "position", server_default=None)


def downgrade() -> None:
    op.drop_column("kitchen_tags", "position")
