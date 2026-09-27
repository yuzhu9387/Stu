"""Personal access tokens for MCP clients acting for one account."""

import sqlalchemy as sa
from alembic import op

revision = "0031_mcp_tokens"
down_revision = "0030_password_sign_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
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
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_tokens_account_id", "mcp_tokens", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_tokens_account_id", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")
