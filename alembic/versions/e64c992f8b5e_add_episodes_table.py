#!/usr/bin/env python3
"""add episodes table

Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/13 09:21:11.000000
Revised: 2026/07/13 09:21:11.000000

Per-episode TMDB catalog data (season, episode number, name, air date),
synced from season payloads so /upcoming/history can list a show's past
aired episodes without a live TMDB call on the request path.

Revision ID: e64c992f8b5e
Revises: fcb87eeae7af
Create Date: 2026-07-13 09:21:11.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e64c992f8b5e"
down_revision: str | Sequence[str] | None = "fcb87eeae7af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("air_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title_id", "season", "episode_number", name="uq_episode_key"),
    )
    op.create_index(op.f("ix_episodes_title_id"), "episodes", ["title_id"], unique=False)
    op.create_index(op.f("ix_episodes_air_date"), "episodes", ["air_date"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_episodes_air_date"), table_name="episodes")
    op.drop_index(op.f("ix_episodes_title_id"), table_name="episodes")
    op.drop_table("episodes")
