#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 09:51:07.121609
Revised: 2026/07/21 09:51:07.121609
"""

"""add user status_colors

Premium per-status accent overrides for Library cards: users.status_colors,
a JSONB map of WatchStatus value -> hex color from premium.PALETTE.

Revision ID: d3e9f6a2b7c1
Revises: c7d8e9f0a1b2
Create Date: 2026-07-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d3e9f6a2b7c1"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("status_colors", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "status_colors")
