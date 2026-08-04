"""make timestamp columns tz-aware

Revision ID: 38cff6b9ccc2
Revises: 65cf117b6ec9
Create Date: 2026-05-20 23:15:41.309920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38cff6b9ccc2'
down_revision: Union[str, Sequence[str], None] = '65cf117b6ec9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NAIVE_COLUMNS = [
    ("conversations", "created_at"),
    ("dialogue_sessions", "created_at"),
    ("dialogue_sessions", "updated_at"),
    ("goals", "created_at"),
    ("habits", "created_at"),
    ("reminders", "created_at"),
    ("reminders", "trigger_time"),
    ("reports", "generated_at"),
    ("tasks", "created_at"),
    ("tasks", "deadline"),
    ("tasks", "updated_at"),
    ("users", "created_at"),
]


def upgrade() -> None:
    for table, column in _NAIVE_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    raise NotImplementedError(
        "Reverting to naive timestamps drops timezone information silently. "
        "Restore from backup if you need to roll back."
    )
