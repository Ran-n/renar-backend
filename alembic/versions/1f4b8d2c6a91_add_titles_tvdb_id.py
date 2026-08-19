#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000
"""

"""add titles.tvdb_id

Adds a second fallback identity for TV shows, alongside tmdb_id/title_key:
TheTVDB v4 series id. Used when TMDB has no match at all for a show (a
genuine outage, or a title TMDB simply doesn't carry) but TheTVDB does —
see users/tvtime_import.py's TVDB fallback and docs/design-decisions.md.
tmdb_id still always wins once it resolves; tvdb_id is never read again
afterward, just left in place as a harmless crosswalk.

Revision ID: 1f4b8d2c6a91
Revises: 6eae4e5ba1c0
Create Date: 2026-08-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f4b8d2c6a91"
down_revision: str | Sequence[str] | None = "6eae4e5ba1c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tvdb_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "uq_title_tvdb",
            ["media_type", "tvdb_id"],
            unique=True,
            sqlite_where=sa.column("tvdb_id").isnot(None),
            postgresql_where=sa.column("tvdb_id").isnot(None),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.drop_index("uq_title_tvdb")
        batch_op.drop_column("tvdb_id")
