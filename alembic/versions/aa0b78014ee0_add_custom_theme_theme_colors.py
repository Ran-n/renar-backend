#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/02 16:30:00.000000
Revised: 2026/08/02 16:30:00.000000
"""

"""add custom_themes.theme_colors

Revision ID: aa0b78014ee0
Revises: a1c9e4f7b3d2
Create Date: 2026-08-02 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "aa0b78014ee0"
down_revision: str | Sequence[str] | None = "a1c9e4f7b3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("custom_themes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("theme_colors", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("custom_themes", schema=None) as batch_op:
        batch_op.drop_column("theme_colors")
