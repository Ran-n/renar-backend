#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/03 00:00:00.000000
Revised: 2026/08/03 00:00:00.000000

rescale ratings 1-10 to 1-100

Data-only migration: multiply every existing non-null rating in
media_items and episode_watches by 10 so that historical 1-10 ratings
remain meaningful on the new 1-100 scale (e.g. an old "8" becomes "80").
No column type or constraint changes — validation is Pydantic-only.

Revision ID: b5f3a1c9d7e2
Revises: 02638e4154de
Create Date: 2026-08-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5f3a1c9d7e2"
down_revision: str | Sequence[str] | None = "02638e4154de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Multiply all existing ratings by 10 (1-10 -> 1-100)."""
    op.execute(sa.text("UPDATE media_items SET rating = rating * 10 WHERE rating IS NOT NULL"))
    op.execute(sa.text("UPDATE episode_watches SET rating = rating * 10 WHERE rating IS NOT NULL"))


def downgrade() -> None:
    # Lossy: divides by 10 (integer division), so a rating of 79 becomes 7,
    # not 7.9 — the original fractional precision is unrecoverable. Expected
    # and fine; this downgrade exists only as a migration safety net, not a
    # precision-preserving rollback.
    op.execute(sa.text("UPDATE media_items SET rating = rating / 10 WHERE rating IS NOT NULL"))
    op.execute(sa.text("UPDATE episode_watches SET rating = rating / 10 WHERE rating IS NOT NULL"))
