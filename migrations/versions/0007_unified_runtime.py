"""Add family ownership and durable agent run storage."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0007_unified_runtime"
down_revision: str | None = "0006_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OWNER_TABLES = (
    "recipes",
    "meal_plans",
    "raw_inputs",
    "media_objects",
    "feedback_events",
    "recipe_ratings",
    "conversations",
)
SHARED_TABLES = ("recipes", "meal_plans")


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    _create_family_tables()
    _add_ownership_columns()
    _add_agent_run_columns()
    _backfill_legacy_ownership()
    _finalize_ownership_columns()
    _finalize_agent_run_columns()
    _create_suggested_actions()


def _create_family_tables() -> None:
    op.create_table(
        "family_memberships",
        _id(),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        _created_at(),
        sa.UniqueConstraint("account_id", "household_id", name="uq_family_membership"),
    )
    op.create_table(
        "family_invites",
        _id(),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "consumed_by_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        _created_at(),
    )


def _add_ownership_columns() -> None:
    for table_name in OWNER_TABLES:
        op.add_column(table_name, sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    for table_name in SHARED_TABLES:
        op.add_column(table_name, sa.Column("visibility", sa.String(16), nullable=True))


def _add_agent_run_columns() -> None:
    op.add_column("agent_runs", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.add_column("agent_runs", sa.Column("household_id", sa.Uuid(), nullable=True))
    op.add_column("agent_runs", sa.Column("transport", sa.String(32), nullable=True))
    op.add_column("agent_runs", sa.Column("idempotency_key", sa.String(160), nullable=True))
    op.add_column("agent_runs", sa.Column("request_json", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("response_json", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("error_code", sa.String(160), nullable=True))
    op.add_column("agent_runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def _backfill_legacy_ownership() -> None:
    connection = op.get_bind()
    households = sa.table(
        "households",
        sa.column("id", sa.Uuid()),
        sa.column("owner_account_id", sa.Uuid()),
    )
    memberships = sa.table(
        "family_memberships",
        sa.column("id", sa.Uuid()),
        sa.column("account_id", sa.Uuid()),
        sa.column("household_id", sa.Uuid()),
        sa.column("role", sa.String(16)),
    )
    household_rows = connection.execute(
        sa.select(households.c.id, households.c.owner_account_id)
    ).all()
    if household_rows:
        connection.execute(
            sa.insert(memberships),
            [
                {
                    "id": uuid4(),
                    "account_id": owner_account_id,
                    "household_id": household_id,
                    "role": "owner",
                }
                for household_id, owner_account_id in household_rows
            ],
        )

    for table_name in OWNER_TABLES:
        target = sa.table(
            table_name,
            sa.column("household_id", sa.Uuid()),
            sa.column("owner_account_id", sa.Uuid()),
        )
        owner_id = (
            sa.select(households.c.owner_account_id)
            .where(households.c.id == target.c.household_id)
            .scalar_subquery()
        )
        connection.execute(sa.update(target).values(owner_account_id=owner_id))

    for table_name in SHARED_TABLES:
        target = sa.table(table_name, sa.column("visibility", sa.String(16)))
        connection.execute(sa.update(target).values(visibility="family"))

    conversations = sa.table(
        "conversations",
        sa.column("id", sa.Uuid()),
        sa.column("owner_account_id", sa.Uuid()),
        sa.column("household_id", sa.Uuid()),
        sa.column("transport", sa.String(32)),
    )
    agent_runs = sa.table(
        "agent_runs",
        sa.column("id", sa.Uuid()),
        sa.column("conversation_id", sa.Uuid()),
        sa.column("account_id", sa.Uuid()),
        sa.column("household_id", sa.Uuid()),
        sa.column("transport", sa.String(32)),
        sa.column("idempotency_key", sa.String(160)),
        sa.column("request_json", sa.Text()),
    )
    conversation_for_run = conversations.c.id == agent_runs.c.conversation_id
    connection.execute(
        sa.update(agent_runs).values(
            account_id=(
                sa.select(conversations.c.owner_account_id)
                .where(conversation_for_run)
                .scalar_subquery()
            ),
            household_id=(
                sa.select(conversations.c.household_id)
                .where(conversation_for_run)
                .scalar_subquery()
            ),
            transport=(
                sa.select(conversations.c.transport).where(conversation_for_run).scalar_subquery()
            ),
            request_json="{}",
        )
    )
    for run_id in connection.execute(sa.select(agent_runs.c.id)).scalars():
        connection.execute(
            sa.update(agent_runs)
            .where(agent_runs.c.id == run_id)
            .values(idempotency_key=f"legacy:{run_id}")
        )


def _finalize_ownership_columns() -> None:
    for table_name in OWNER_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("owner_account_id", existing_type=sa.Uuid(), nullable=False)
            batch_op.create_foreign_key(
                f"fk_{table_name}_owner_account_id",
                "accounts",
                ["owner_account_id"],
                ["id"],
                ondelete="CASCADE",
            )
    for table_name in SHARED_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "visibility",
                existing_type=sa.String(16),
                nullable=False,
                server_default="family",
            )


def _finalize_agent_run_columns() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column("account_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.alter_column("household_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.alter_column("transport", existing_type=sa.String(32), nullable=False)
        batch_op.alter_column("idempotency_key", existing_type=sa.String(160), nullable=False)
        batch_op.alter_column(
            "request_json",
            existing_type=sa.Text(),
            nullable=False,
            server_default="{}",
        )
        batch_op.create_foreign_key(
            "fk_agent_runs_account_id",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_agent_runs_household_id",
            "households",
            ["household_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_agent_run_idempotency",
            ["account_id", "transport", "idempotency_key"],
        )


def _create_suggested_actions() -> None:
    op.create_table(
        "suggested_actions",
        _id(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
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
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "consumed_by_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        _created_at(),
    )


def downgrade() -> None:
    op.drop_table("suggested_actions")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint("uq_agent_run_idempotency", type_="unique")
        batch_op.drop_constraint("fk_agent_runs_household_id", type_="foreignkey")
        batch_op.drop_constraint("fk_agent_runs_account_id", type_="foreignkey")
        for column_name in (
            "completed_at",
            "started_at",
            "error_code",
            "response_json",
            "request_json",
            "idempotency_key",
            "transport",
            "household_id",
            "account_id",
        ):
            batch_op.drop_column(column_name)

    for table_name in reversed(OWNER_TABLES):
        with op.batch_alter_table(table_name) as batch_op:
            if table_name in SHARED_TABLES:
                batch_op.drop_column("visibility")
            batch_op.drop_constraint(f"fk_{table_name}_owner_account_id", type_="foreignkey")
            batch_op.drop_column("owner_account_id")

    op.drop_table("family_invites")
    op.drop_table("family_memberships")
