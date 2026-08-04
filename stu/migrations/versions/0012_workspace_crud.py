"""Add editable recipe metadata, plan metadata, and household todos."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_workspace_crud"
down_revision: str | None = "0011_lark_runtime_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.add_column(
            sa.Column("meal_type", sa.String(32), nullable=False, server_default="dinner")
        )
        batch_op.add_column(
            sa.Column("prep_minutes", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("cook_minutes", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("suitable_age_years", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("image_url", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )

    with op.batch_alter_table("meal_plans") as batch_op:
        batch_op.add_column(
            sa.Column("title", sa.String(200), nullable=False, server_default="Weekly plan")
        )
        batch_op.add_column(
            sa.Column("generated_by_ai", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )

    op.create_table(
        "todos",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "owner_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="family"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("category IN ('grocery', 'todo')", name="ck_todos_category"),
        sa.CheckConstraint("visibility IN ('private', 'family')", name="ck_todos_visibility"),
    )
    op.create_index("ix_todos_household_id", "todos", ["household_id"])
    op.create_index("ix_todos_owner_account_id", "todos", ["owner_account_id"])


def downgrade() -> None:
    op.drop_table("todos")
    with op.batch_alter_table("meal_plans") as batch_op:
        for column in ("updated_at", "created_at", "generated_by_ai", "title"):
            batch_op.drop_column(column)
    with op.batch_alter_table("recipes") as batch_op:
        for column in (
            "updated_at",
            "image_url",
            "suitable_age_years",
            "cook_minutes",
            "prep_minutes",
            "meal_type",
        ):
            batch_op.drop_column(column)
