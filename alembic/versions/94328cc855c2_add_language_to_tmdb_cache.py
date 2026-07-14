#!/usr/bin/env python3
"""add language to tmdb cache

Authors: Ran# <ran.hash@proton.me>

Localized detail/season overviews: tmdb_cache rows are now keyed per app
language too, so each locale gets its own cached TMDB payload alongside the
English one that still syncs the typed Title/Episode columns.

Revision ID: 94328cc855c2
Revises: d3f7b8a1c2e9
Create Date: 2026-07-14 00:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "94328cc855c2"
down_revision: str | Sequence[str] | None = "d3f7b8a1c2e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tmdb_cache", sa.Column("language", sa.String(length=5), nullable=False, server_default="en"))
    op.alter_column("tmdb_cache", "language", server_default=None)
    op.drop_constraint("uq_tmdb_cache_key", "tmdb_cache", type_="unique")
    op.create_unique_constraint("uq_tmdb_cache_key", "tmdb_cache", ["title_id", "kind", "season", "language"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_tmdb_cache_key", "tmdb_cache", type_="unique")
    op.create_unique_constraint("uq_tmdb_cache_key", "tmdb_cache", ["title_id", "kind", "season"])
    op.drop_column("tmdb_cache", "language")
