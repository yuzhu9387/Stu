"""Recipe detail fields from frame 36:1030 that had no column yet.

Difficulty, cuisine, English name, ingredient grouping, per-step titles and
timing, reheating instructions, nutrition and ratings already have columns from
0015. Only the hero photo link is new: uploads are not wired, so a pasted URL
is what the screen can actually show today.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_recipe_detail_fields"
down_revision: str | None = "0023_collection_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kitchen_recipes", sa.Column("hero_image_url", sa.String(length=2000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("kitchen_recipes", "hero_image_url")
