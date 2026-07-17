#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 19:29:48.974185
Revised: 2026/07/17 19:32:52.669223
"""

"""add trust_proxy_headers and exempt_ips to site_settings

Revision ID: 7bc87a340d08
Revises: b7c3f5a91d02
Create Date: 2026-07-17 19:29:48.974185

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7bc87a340d08"
down_revision: str | Sequence[str] | None = "b7c3f5a91d02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trust_proxy_headers", sa.Boolean(), server_default="false", nullable=False))
        batch_op.add_column(
            sa.Column(
                "exempt_ips",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default='["127.0.0.1", "::1"]',
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("exempt_ips")
        batch_op.drop_column("trust_proxy_headers")
