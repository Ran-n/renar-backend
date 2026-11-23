#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:03.483388
Revised: 2026/11/22 01:51:03.483388
"""

"""add users.terms_accepted_at

users.terms_accepted_at: when the user ticked the sign-up box accepting the
Terms of Service and the Privacy Policy and confirming they're 14 or older.
NULL for accounts created before the box existed.

Revision ID: d7e1a4c9f2b3
Revises: c9e4a1b63f58
Create Date: 2026-11-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e1a4c9f2b3"
down_revision: str | Sequence[str] | None = "c9e4a1b63f58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "terms_accepted_at")
