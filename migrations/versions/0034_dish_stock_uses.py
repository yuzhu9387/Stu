"""A dish cooked from several fridge foods remembers what it takes from each."""

import sqlalchemy as sa
from alembic import op

revision = "0034_dish_stock_uses"
down_revision = "0033_secondary_food_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meal_components", sa.Column("uses", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("meal_components", "uses")
