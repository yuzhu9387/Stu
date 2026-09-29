"""A dish keeps its own ingredients and time; a changed meal keeps its note."""

import sqlalchemy as sa
from alembic import op

revision = "0036_dish_details_changed"
down_revision = "0035_dish_secondary_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meals", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("meal_components", sa.Column("ingredients", sa.JSON(), nullable=True))
    op.add_column("meal_components", sa.Column("active_minutes", sa.Numeric(10, 2), nullable=True))
    op.add_column("meal_components", sa.Column("elapsed_minutes", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("meal_components", "elapsed_minutes")
    op.drop_column("meal_components", "active_minutes")
    op.drop_column("meal_components", "ingredients")
    op.drop_column("meals", "note")
