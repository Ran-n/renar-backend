#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/21 00:00:00.000000
Revised: 2026/08/21 16:27:43.749462
"""

"""add turnstile_dev_hostnames to site_settings

Revision ID: f6d5c84349df
Revises: dee43d77d3ca
Create Date: 2026-08-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6d5c84349df"
down_revision: str | Sequence[str] | None = "dee43d77d3ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "turnstile_dev_hostnames",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("turnstile_dev_hostnames")
