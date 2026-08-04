"""infra bundle: add events, drop daily_plans/habit_records/time_entries/meeting_notes, add task.habit_id, time_slots.date

Revision ID: 65cf117b6ec9
Revises: c05044bcb82c
Create Date: 2026-05-20 22:02:01.530600

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '65cf117b6ec9'
down_revision: Union[str, Sequence[str], None] = 'c05044bcb82c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. events
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("type", sa.String(50), nullable=False, index=True),
        sa.Column("entity_type", sa.String(20), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("payload", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_index("ix_events_entity", "events", ["entity_type", "entity_id"])

    # 2. task.habit_id FK
    op.add_column("tasks", sa.Column("habit_id", sa.Integer(), sa.ForeignKey("habits.id"), nullable=True))

    # 3. time_slots: add date, drop daily_plan_id
    op.add_column("time_slots", sa.Column("date", sa.Date(), nullable=True))
    # populate date from existing daily_plans rows if any, then enforce NOT NULL
    op.execute(
        "UPDATE time_slots ts SET date = dp.date FROM daily_plans dp WHERE ts.daily_plan_id = dp.id"
    )
    op.alter_column("time_slots", "date", nullable=False)
    op.drop_constraint("time_slots_daily_plan_id_fkey", "time_slots", type_="foreignkey")
    op.drop_column("time_slots", "daily_plan_id")

    # 4. drop tables
    op.drop_table("habit_records")
    op.drop_table("time_entries")
    op.drop_table("meeting_notes")
    op.drop_table("daily_plans")


def downgrade() -> None:
    raise NotImplementedError(
        "This migration's downgrade is not supported because it drops 4 tables "
        "(habit_records, time_entries, meeting_notes, daily_plans) whose data cannot "
        "be reconstructed. Restore from backup if you need to roll back."
    )
