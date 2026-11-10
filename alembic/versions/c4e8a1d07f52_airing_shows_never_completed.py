#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 15:59:25.523371
Revised: 2026/11/09 15:59:25.523371
"""

"""airing shows are never completed

Data-only: a still-airing show the user was up to date on used to
auto-complete (shown as "Caught up"). It now stays "watching" until the
show ends (see catalog/progress.py), so every existing completed entry on a
show whose TMDB status is known and not ended moves back to watching. The
status list is inlined (not imported from the app) so this migration stays
self-contained.

Revision ID: c4e8a1d07f52
Revises: 88137cd72bc2
Create Date: 2026-11-09 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1d07f52"
down_revision: str | Sequence[str] | None = "88137cd72bc2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE media_items AS m
            SET status = 'watching'
            FROM titles AS t
            WHERE t.id = m.title_id
              AND t.media_type = 'tv_show'
              AND m.status = 'completed'
              AND t.show_status IS NOT NULL
              AND t.show_status NOT IN ('Ended', 'Canceled')
            """
        )
    )


def downgrade() -> None:
    # Not reversible: which of these were auto-completed vs set by hand
    # wasn't recorded, and either way the old state was the wrong one.
    pass
