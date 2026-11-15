#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:43.036285
Revised: 2026/11/14 00:22:43.036285
"""

"""add season_ratings table

A user's own 1-100 grade for one whole season of a show in their library:
one row per (library entry, season).

Revision ID: b8d3f0a52e47
Revises: a7c2e9f41d36
Create Date: 2026-11-13 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d3f0a52e47"
down_revision: str | Sequence[str] | None = "a7c2e9f41d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "season_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 100", name="ck_season_rating_range"),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_item_id", "season", name="uq_item_season_rating"),
    )
    op.create_index(op.f("ix_season_ratings_media_item_id"), "season_ratings", ["media_item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_season_ratings_media_item_id"), table_name="season_ratings")
    op.drop_table("season_ratings")
