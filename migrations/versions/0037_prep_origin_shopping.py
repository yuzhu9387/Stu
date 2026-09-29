"""A + Prep dish remembers it was cooked from the fridge."""

import sqlalchemy as sa
from alembic import op

revision = "0037_prep_origin_shopping"
down_revision = "0036_dish_details_changed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prep_tasks", sa.Column("origin", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("prep_tasks", "origin")
