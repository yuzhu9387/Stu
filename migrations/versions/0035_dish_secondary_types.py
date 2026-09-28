"""A dish on a plate can name its own other food groups."""

import sqlalchemy as sa
from alembic import op

revision = "0035_dish_secondary_types"
down_revision = "0034_dish_stock_uses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meal_components", sa.Column("secondary_types", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("meal_components", "secondary_types")
