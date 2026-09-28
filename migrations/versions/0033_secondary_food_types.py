"""A dish or food's other food groups: buns are Carbs, with Protein and Vegetables."""

import sqlalchemy as sa
from alembic import op

revision = "0033_secondary_food_types"
down_revision = "0032_child_birthday"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kitchen_recipes", sa.Column("secondary_types", sa.JSON(), nullable=True))
    op.add_column("food_items", sa.Column("secondary_types", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("food_items", "secondary_types")
    op.drop_column("kitchen_recipes", "secondary_types")
