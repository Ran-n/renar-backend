#!/usr/bin/env python3
"""add tmdb cache, external images and title detail columns

Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:18.565753
Revised: 2026/07/10 18:19:21.588899

TMDB write-through cache: raw payloads for tracked titles persist in
tmdb_cache so detail pages survive TMDB outages and restarts. Typed detail
facts (overview, tagline, show_status, next_episode_air_date,
total_seasons) live on titles. external_images maps TMDB posters/stills
and Open Library covers to the content-addressed image store, replacing
the loose on-disk caches.

Revision ID: b8e4d27a91c5
Revises: 9c4e2d81f5a3
Create Date: 2026-07-10 16:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "b8e4d27a91c5"
down_revision: str | Sequence[str] | None = "9c4e2d81f5a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("titles", sa.Column("total_seasons", sa.Integer(), nullable=True))
    op.add_column("titles", sa.Column("overview", sa.Text(), nullable=True))
    op.add_column("titles", sa.Column("tagline", sa.String(length=500), nullable=True))
    op.add_column("titles", sa.Column("show_status", sa.String(length=30), nullable=True))
    op.add_column("titles", sa.Column("next_episode_air_date", sa.Date(), nullable=True))

    op.create_table(
        "tmdb_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title_id", "kind", "season", name="uq_tmdb_cache_key"),
    )
    op.create_index(op.f("ix_tmdb_cache_title_id"), "tmdb_cache", ["title_id"], unique=False)

    op.create_table(
        "external_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "key", name="uq_external_image"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("external_images")
    op.drop_index(op.f("ix_tmdb_cache_title_id"), table_name="tmdb_cache")
    op.drop_table("tmdb_cache")
    op.drop_column("titles", "next_episode_air_date")
    op.drop_column("titles", "show_status")
    op.drop_column("titles", "tagline")
    op.drop_column("titles", "overview")
    op.drop_column("titles", "total_seasons")
