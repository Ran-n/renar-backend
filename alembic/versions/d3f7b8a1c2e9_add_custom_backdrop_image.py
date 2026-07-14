"""add custom backdrop image

Premium custom-backdrop override, same shape as the existing custom-poster
override: media_items.custom_backdrop_image_id points at the content-
addressed image store; the shared titles row is never touched.

Revision ID: d3f7b8a1c2e9
Revises: b4c6e8f2a3d7
Create Date: 2026-07-14 19:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f7b8a1c2e9"
down_revision: str | Sequence[str] | None = "b4c6e8f2a3d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("media_items", sa.Column("custom_backdrop_image_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_media_items_custom_backdrop_image", "media_items", "images", ["custom_backdrop_image_id"], ["id"]
    )
    op.create_index(
        "ix_media_items_custom_backdrop_image_id", "media_items", ["custom_backdrop_image_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_media_items_custom_backdrop_image_id", table_name="media_items")
    op.drop_constraint("fk_media_items_custom_backdrop_image", "media_items", type_="foreignkey")
    op.drop_column("media_items", "custom_backdrop_image_id")
