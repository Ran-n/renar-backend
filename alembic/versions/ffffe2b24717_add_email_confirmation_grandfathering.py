#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 14:22:00.000000
Revised: 2026/07/21 09:51:07.392374
"""

"""add email confirmation grandfathering

Fixes a real bug in migration ee151fb9d02c's "no grandfathering" design: the
login grace period (routers/auth.py's login) is measured from
User.created_at, not from when this feature shipped. Any account already
older than EMAIL_CONFIRMATION_GRACE_DAYS (7) at migration time got zero
actual grace period — it would be blocked at its very next login, not given
a real window to notice and confirm. On a deployment with an established
user base, this migration alone would have silently locked out everyone.

email_confirmation_grandfathered=True (backfilled here for every row that
already exists) exempts an account from that login block AND from the
14-day unconfirmed-account cleanup (users/email_confirmation.py's
cleanup_unconfirmed_accounts), permanently, without marking it
email_confirmed — a grandfathered-but-unconfirmed account still doesn't
count toward /stats/ranking, which is the actual point of the feature.
Only accounts that existed before this migration get the exemption; every
account created afterward is subject to the login gate and cleanup exactly
as before.

Revision ID: ffffe2b24717
Revises: 4220e67045f7
Create Date: 2026-07-20 14:22:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ffffe2b24717"
down_revision: str | Sequence[str] | None = "4220e67045f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("email_confirmation_grandfathered", sa.Boolean(), nullable=False, server_default="false")
        )
    # Every row that exists at migration time predates this feature by
    # definition — mark all of them, not just the currently-unconfirmed
    # ones (harmless for an already-confirmed row; keeps the semantics
    # simple: "existed before rollout" rather than "existed before rollout
    # AND happened to still be unconfirmed at this exact moment").
    op.execute("UPDATE users SET email_confirmation_grandfathered = true")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_confirmation_grandfathered")
