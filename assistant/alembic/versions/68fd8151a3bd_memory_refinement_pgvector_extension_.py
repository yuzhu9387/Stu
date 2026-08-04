"""memory refinement: pgvector extension + episodic_embeddings

Revision ID: 68fd8151a3bd
Revises: 38cff6b9ccc2
Create Date: 2026-05-26 15:04:10.514289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68fd8151a3bd'
down_revision: Union[str, Sequence[str], None] = "38cff6b9ccc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "episodic_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Placeholder column; replaced below with the real vector(1024).
        sa.Column("embedding_placeholder", sa.dialects.postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("ALTER TABLE episodic_embeddings DROP COLUMN embedding_placeholder")
    op.execute("ALTER TABLE episodic_embeddings ADD COLUMN embedding vector(1024) NOT NULL")
    op.create_index("ix_episodic_embeddings_user", "episodic_embeddings", ["user_id"])
    op.execute(
        "CREATE INDEX ix_episodic_embeddings_vec ON episodic_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_episodic_embeddings_vec", table_name="episodic_embeddings")
    op.drop_index("ix_episodic_embeddings_user", table_name="episodic_embeddings")
    op.drop_table("episodic_embeddings")
    # Don't drop the vector extension — leave it for other potential consumers.
