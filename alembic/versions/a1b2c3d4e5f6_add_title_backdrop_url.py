#!/usr/bin/env python3
"""add title backdrop_url

Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/14 00:00:00.000000
Revised: 2026/07/14 00:00:00.000000

Landscape backdrop art for full-bleed hero display (Home's "continue
watching" card), stored alongside the existing portrait poster_url.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("titles", sa.Column("backdrop_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("titles", "backdrop_url")
