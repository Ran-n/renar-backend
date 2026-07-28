#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/28 11:14:48.610190
Revised: 2026/07/28 11:14:48.610190
"""

"""add invite_codes.last_used_at

Adds InviteCode.last_used_at, set in routers/auth.py's register() whenever a
redemption increments uses. Registration already refuses a redemption once
uses >= max_uses, so for an exhausted code this column holds exactly the
timestamp it became exhausted — the admin invites page uses it to tell
whether a code that's both past its expires_at and at its use cap hit one
boundary before the other, instead of always labeling it "expired" just
because that check happens to run first.

No backfill: for any code already exhausted before this migration, the
timestamp of the use that filled it was never recorded, so it's left NULL
(the admin page falls back to labeling those "expired", the same behavior
as before this migration).

Revision ID: a73fd0cecbb5
Revises: 275461ed120c
Create Date: 2026-07-28 11:14:48.610190

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a73fd0cecbb5"
down_revision: str | Sequence[str] | None = "275461ed120c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.drop_column("last_used_at")
