"""add premium user fields and custom posters

Premium accounts: users.premium_until (active while in the future),
admin-granted verified badge with a verification_requested flag, and the
two palette colors (avatar ring + username text). Library entries gain
custom_poster_image_id — a per-user poster override pointing at the
content-addressed image store; the shared titles row is never touched.

Revision ID: c7f2a94e08d1
Revises: b8e4d27a91c5
Create Date: 2026-07-10 18:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f2a94e08d1"
down_revision: str | Sequence[str] | None = "b8e4d27a91c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("premium_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("verification_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("ring_color", sa.String(length=7), nullable=True))
    op.add_column("users", sa.Column("name_color", sa.String(length=7), nullable=True))

    op.add_column("media_items", sa.Column("custom_poster_image_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_media_items_custom_poster_image", "media_items", "images", ["custom_poster_image_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_media_items_custom_poster_image", "media_items", type_="foreignkey")
    op.drop_column("media_items", "custom_poster_image_id")
    op.drop_column("users", "name_color")
    op.drop_column("users", "ring_color")
    op.drop_column("users", "verification_requested")
    op.drop_column("users", "verified")
    op.drop_column("users", "premium_until")
