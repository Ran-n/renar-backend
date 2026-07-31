#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/29 16:10:19.851612
Revised: 2026/07/29 16:10:19.851612
"""

"""add email confirmation bypassed flag

Purely informational marker: True when a user's email_confirmed was set to
True without them ever completing the code round trip (registered while
SiteSettings.email_confirmation_enabled was off, or an admin disabled that
toggle while the account was still unconfirmed). Nothing re-gates on it —
see User.email_confirmation_bypassed's docstring in models.py.

Revision ID: 6d15f435ffcf
Revises: 1b63409d9417
Create Date: 2026-07-29 16:10:19.851612

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6d15f435ffcf"
down_revision: str | Sequence[str] | None = "1b63409d9417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("email_confirmation_bypassed", sa.Boolean(), nullable=False, server_default="false")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_confirmation_bypassed")
