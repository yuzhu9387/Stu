"""Create meal plans and shopping lists."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_planning"
down_revision: str | None = "0003_imports_and_recipes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meal_plans",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_meal_plans_household_id", "meal_plans", ["household_id"])
    op.create_table(
        "meal_plan_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("meal_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(32), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_name", sa.String(300), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("ingredients_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_meal_plan_items_plan_id", "meal_plan_items", ["plan_id"])
    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("meal_plans.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "shopping_list_id",
            sa.Uuid(),
            sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_shopping_items_shopping_list_id", "shopping_items", ["shopping_list_id"])


def downgrade() -> None:
    op.drop_table("shopping_items")
    op.drop_table("shopping_lists")
    op.drop_table("meal_plan_items")
    op.drop_table("meal_plans")
