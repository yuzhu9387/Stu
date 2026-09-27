"""Email and password sign-in, with a lockout after repeated failures."""

import sqlalchemy as sa
from alembic import op

revision = "0030_password_sign_in"
down_revision = "0029_pinned_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("failed_sign_ins", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("accounts", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "locked_until")
    op.drop_column("accounts", "failed_sign_ins")
    op.drop_column("accounts", "password_hash")
