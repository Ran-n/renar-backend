#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 09:41:28.201238
Revised: 2026/07/17 09:41:28.201238
"""

"""add periodic task toggles to site_settings

Revision ID: c1e6a4f92d38
Revises: ae65f1be8d32
Create Date: 2026-07-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e6a4f92d38"
down_revision: str | Sequence[str] | None = "ae65f1be8d32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("episode_check_enabled", sa.Boolean(), server_default="true", nullable=False))
        batch_op.add_column(sa.Column("film_check_enabled", sa.Boolean(), server_default="true", nullable=False))
        batch_op.add_column(sa.Column("bans_check_enabled", sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("bans_check_enabled")
        batch_op.drop_column("film_check_enabled")
        batch_op.drop_column("episode_check_enabled")
