#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 12:00:00.000000
Revised: 2026/07/21 09:51:06.490707
"""

"""add premium ranking toggle to site_settings

Revision ID: a1f5e8c3d629
Revises: b4c6a1e0f923
Create Date: 2026-07-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f5e8c3d629"
down_revision: str | Sequence[str] | None = "b4c6a1e0f923"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("premium_ranking_enabled", sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("premium_ranking_enabled")
