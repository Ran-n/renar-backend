#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 00:00:00.000000
Revised: 2026/07/21 09:51:06.868230
"""

"""add premium feature toggles to site_settings

Revision ID: b4c6a1e0f923
Revises: d3e9f6a2b7c1
Create Date: 2026-07-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c6a1e0f923"
down_revision: str | Sequence[str] | None = "d3e9f6a2b7c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "premium_style_enabled",
    "premium_verification_enabled",
    "premium_background_enabled",
    "premium_themes_enabled",
    "premium_progress_style_enabled",
    "premium_episode_label_enabled",
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        for column in _COLUMNS:
            batch_op.add_column(sa.Column(column, sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        for column in _COLUMNS:
            batch_op.drop_column(column)
