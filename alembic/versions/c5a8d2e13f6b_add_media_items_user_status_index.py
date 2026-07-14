"""add media_items user_id/status composite index

GET /media filters on (user_id, status) whenever a status tab (e.g. "in
progress"/watching) is selected; only user_id was indexed, so Postgres had
to index-scan every one of the user's entries and filter status row by row.

Revision ID: c5a8d2e13f6b
Revises: b1c9d4e7f083
Create Date: 2026-07-14 21:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5a8d2e13f6b"
down_revision: str | Sequence[str] | None = "b1c9d4e7f083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_media_items_user_id_status", "media_items", ["user_id", "status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_media_items_user_id_status", table_name="media_items")
