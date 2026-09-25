"""Keep the household allergy list in the order it was entered.

Settings renders the list joined into one line, so the order is user-visible
and must survive the round trip.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_allergy_position"
down_revision: str | None = "0021_prep_output_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "household_allergies",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("household_allergies", "position", server_default=None)


def downgrade() -> None:
    op.drop_column("household_allergies", "position")
