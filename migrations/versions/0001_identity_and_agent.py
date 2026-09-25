"""Create identity and agent audit tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_identity_and_agent"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _account_foreign_key(*, unique: bool = False) -> sa.Column[object]:
    return sa.Column(
        "account_id",
        sa.Uuid(),
        sa.ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=unique,
    )


def upgrade() -> None:
    op.create_table(
        "accounts",
        _id(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        _created_at(),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"])
    op.create_table(
        "households",
        _id(),
        sa.Column(
            "owner_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        _created_at(),
    )
    _create_identity_tables()
    _create_conversation_tables()


def _create_identity_tables() -> None:
    op.create_table(
        "magic_links",
        _id(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_index("ix_magic_links_email", "magic_links", ["email"])
    op.create_table(
        "lark_link_codes",
        _id(),
        _account_foreign_key(),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_table(
        "lark_identities",
        _id(),
        _account_foreign_key(unique=True),
        sa.Column("open_id", sa.String(128), nullable=False, unique=True),
        _created_at(),
    )
    op.create_table(
        "web_sessions",
        _id(),
        _account_foreign_key(),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
    )


def _create_conversation_tables() -> None:
    op.create_table(
        "conversations",
        _id(),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transport", sa.String(32), nullable=False),
        _created_at(),
    )
    op.create_index("ix_conversations_household_id", "conversations", ["household_id"])
    op.create_table(
        "conversation_messages",
        _id(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _created_at(),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id"],
    )
    op.create_table(
        "agent_runs",
        _id(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        _created_at(),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_table(
        "agent_run_steps",
        _id(),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        _created_at(),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_step_sequence"),
    )
    op.create_index("ix_agent_run_steps_run_id", "agent_run_steps", ["run_id"])


def downgrade() -> None:
    for table in (
        "agent_run_steps",
        "agent_runs",
        "conversation_messages",
        "conversations",
        "web_sessions",
        "lark_identities",
        "lark_link_codes",
        "magic_links",
        "households",
        "accounts",
    ):
        op.drop_table(table)
