#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 19:59:59.312804
Revised: 2026/07/17 19:59:59.312804
"""

"""add tmdb_db_cache_hours to site_settings

Revision ID: 2267d348213e
Revises: 45a9dba29ff9
Create Date: 2026-07-17 19:59:59.312804

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2267d348213e"
down_revision: str | Sequence[str] | None = "45a9dba29ff9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tmdb_db_cache_hours", sa.Integer(), server_default="24", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("tmdb_db_cache_hours")
