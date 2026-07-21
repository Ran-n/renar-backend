#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/19 00:00:00.000000
Revised: 2026/07/21 09:51:06.367638
"""

"""add turnstile_enabled to site_settings

Revision ID: 86c66fe120eb
Revises: a3f8c1e97b52
Create Date: 2026-07-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86c66fe120eb"
down_revision: str | Sequence[str] | None = "a3f8c1e97b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("turnstile_enabled", sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("turnstile_enabled")
