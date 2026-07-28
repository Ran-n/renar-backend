#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/28 12:45:00.000000
Revised: 2026/07/28 12:45:00.000000
"""

"""add images.source_url

Adds Image.source_url, set in image_service.image_row_for() whenever a
custom poster/backdrop/episode-still is picked from a TMDB alternate rather
than uploaded. Lets the frontend's alternates picker mark which tile is the
current pick by comparing this to the alternate's own URL, instead of never
being able to highlight anything (a raw content hash has no way back to the
TMDB URL it was downloaded from).

No backfill: existing custom poster/backdrop/still images were downloaded
before this column existed, so their source_url is left NULL — the picker
just won't highlight a current tile for those until the user picks a new one.

Revision ID: 40c05acfeddb
Revises: a73fd0cecbb5
Create Date: 2026-07-28 12:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "40c05acfeddb"
down_revision: str | Sequence[str] | None = "a73fd0cecbb5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("images", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("images", schema=None) as batch_op:
        batch_op.drop_column("source_url")
