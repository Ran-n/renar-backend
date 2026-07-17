#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 09:41:28.124449
Revised: 2026/07/17 09:41:28.124449
"""

"""invite_codes max_uses nullable (unlimited-use codes)

Revision ID: ae65f1be8d32
Revises: b9c3e1f84a2d
Create Date: 2026-07-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae65f1be8d32"
down_revision: str | Sequence[str] | None = "b9c3e1f84a2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.alter_column("max_uses", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.alter_column("max_uses", existing_type=sa.Integer(), nullable=False)
