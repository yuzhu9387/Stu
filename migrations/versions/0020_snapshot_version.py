"""Record the version number a plan snapshot pinned.

A guidance rule or knowledge document can, through the API, change content
without bumping its version. The preserved version row then has to take a free
slot, which would otherwise change the number the snapshot reports. Storing the
pinned number on the link keeps the transport stable either way.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_snapshot_version"
down_revision: str | None = "0019_tag_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("plan_guidance_snapshots", "plan_knowledge_snapshots"):
        op.add_column(
            table, sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        op.alter_column(table, "version", server_default=None)


def downgrade() -> None:
    for table in ("plan_guidance_snapshots", "plan_knowledge_snapshots"):
        op.drop_column(table, "version")
