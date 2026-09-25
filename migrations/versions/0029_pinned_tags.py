"""Recipe tags the household pins to the front of the Recipe Book filters."""

import sqlalchemy as sa
from alembic import op

revision = "0029_pinned_tags"
down_revision = "0028_confirmation_recurring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL means never chosen: the meals and the child's tags stay pinned.
    op.add_column("household_kitchen_settings", sa.Column("pinned_tags", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("household_kitchen_settings", "pinned_tags")
