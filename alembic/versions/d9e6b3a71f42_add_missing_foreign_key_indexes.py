"""add missing foreign key indexes

Every FK that is queried on its own now has an index. gc_image() counts
references from users.avatar_id, media_items.custom_poster_image_id and
external_images.image_id on every avatar/poster change; ORM cascades scan
notifications.media_item_id on every library-entry delete; genre-side
lookups on title_genres only had the (title_id, genre_id) composite PK.

Revision ID: d9e6b3a71f42
Revises: c7f2a94e08d1
Create Date: 2026-07-12 02:50:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e6b3a71f42"
down_revision: str | Sequence[str] | None = "c7f2a94e08d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = [
    ("ix_users_avatar_id", "users", "avatar_id"),
    ("ix_media_items_custom_poster_image_id", "media_items", "custom_poster_image_id"),
    ("ix_external_images_image_id", "external_images", "image_id"),
    ("ix_notifications_media_item_id", "notifications", "media_item_id"),
    ("ix_title_genres_genre_id", "title_genres", "genre_id"),
]


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
