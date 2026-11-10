#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 16:20:15.200424
Revised: 2026/11/09 16:20:41.561735
"""

"""add app_releases table

Android APKs uploaded by renar-frontend's ``uv run build apk --split
--publish`` and served to in-app updates (see app_releases.py).

Revision ID: d9b3f6a2c1e7
Revises: c4e8a1d07f52
Create Date: 2026-11-09 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9b3f6a2c1e7"
down_revision: str | Sequence[str] | None = "c4e8a1d07f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("blake3", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blake3"),
        sa.UniqueConstraint("sha256"),
        sa.UniqueConstraint("platform", "version", name="uq_app_releases_platform_version"),
    )


def downgrade() -> None:
    op.drop_table("app_releases")
