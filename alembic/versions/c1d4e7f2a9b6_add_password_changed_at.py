#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/23 00:00:00.000000
Revised: 2026/07/23 00:00:00.000000
"""

"""add password_changed_at

users.password_changed_at: bumped on every password change (self-service or
admin reset) so get_current_user can reject any bearer token issued before
that moment — a leaked token stops working the instant its password is
replaced instead of staying valid for the rest of its expiry window.

Revision ID: c1d4e7f2a9b6
Revises: b7f3d0a91c4e
Create Date: 2026-07-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d4e7f2a9b6"
down_revision: str | Sequence[str] | None = "b7f3d0a91c4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "password_changed_at")
