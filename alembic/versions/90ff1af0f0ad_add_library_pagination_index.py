"""add library pagination index

GET /media now supports limit/offset so "All" (the one filter with no
media_type/status WHERE clause) doesn't have to fetch the whole library to
paint the first screen. The query still sorts by updated_at, so paginating a
large, otherwise-unfiltered library needs an index covering that sort — just
user_id was indexed before.

Revision ID: 90ff1af0f0ad
Revises: 54c6bdd2347a
Create Date: 2026-07-15 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "90ff1af0f0ad"
down_revision: str | Sequence[str] | None = "54c6bdd2347a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_media_items_user_id_updated_at", "media_items", ["user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_media_items_user_id_updated_at", table_name="media_items")
