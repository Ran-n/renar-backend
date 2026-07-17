#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 13:05:00.000000
Revised: 2026/07/17 13:04:42.204771
"""

"""invite_codes created_by_admin (HTTP Basic admin username, not a users.id FK)

Revision ID: 23dd41789cea
Revises: c1e6a4f92d38
Create Date: 2026-07-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "23dd41789cea"
down_revision: str | Sequence[str] | None = "c1e6a4f92d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("created_by_admin", sa.String(length=150), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.drop_column("created_by_admin")
