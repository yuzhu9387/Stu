"""A + Prep dish remembers it was cooked from the fridge; the shopping note
on the fridge door keeps its rows."""

import sqlalchemy as sa
from alembic import op

revision = "0037_prep_origin_shopping"
down_revision = "0036_dish_details_changed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prep_tasks", sa.Column("origin", sa.String(16), nullable=True))
    op.create_table(
        "shopping_note_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=True),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "legacy_id", name="uq_shopping_note_item_legacy"),
    )
    op.create_index(
        op.f("ix_shopping_note_items_household_id"),
        "shopping_note_items",
        ["household_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shopping_note_items_household_id"), table_name="shopping_note_items")
    op.drop_table("shopping_note_items")
    op.drop_column("prep_tasks", "origin")
