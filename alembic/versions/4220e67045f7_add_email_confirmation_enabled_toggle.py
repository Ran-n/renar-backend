#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 14:00:00.000000
Revised: 2026/07/21 09:51:06.239535
"""

"""add email_confirmation_enabled toggle to site_settings

Admin-configurable kill switch for the registration/email-change
confirmation-code flow (see users/email_confirmation.py) — same pattern as
site_settings.turnstile_enabled. Defaults to True (the feature stays on for
existing deployments unless an admin turns it off).

Revision ID: 4220e67045f7
Revises: ee151fb9d02c
Create Date: 2026-07-20 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4220e67045f7"
down_revision: str | Sequence[str] | None = "ee151fb9d02c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("email_confirmation_enabled", sa.Boolean(), nullable=False, server_default="true")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("email_confirmation_enabled")
