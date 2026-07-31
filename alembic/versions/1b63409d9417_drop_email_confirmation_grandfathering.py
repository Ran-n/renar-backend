#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/29 16:03:24.861483
Revised: 2026/07/29 16:03:24.861483
"""

"""drop email confirmation grandfathering

Replaces migration ffffe2b24717's exemption flag with a direct, permanent
fix: every account that already existed at rollout is bulk-marked
email_confirmed=True (instead of merely exempted from the login-gate block
and cleanup while staying unconfirmed forever). Simpler to reason about —
one boolean instead of two — and these are real, pre-existing accounts, not
throwaway signups, so there's no ranking-inflation concern in marking them
confirmed outright. `anxo` (id 49, anxod.ledo@gmail.com) is deliberately
excluded so the confirm-email flow keeps a real account to exercise it
against.

Revision ID: 1b63409d9417
Revises: 68156a912acf
Create Date: 2026-07-29 16:02:49.121166

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b63409d9417"
down_revision: str | Sequence[str] | None = "68156a912acf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE users SET email_confirmed = true WHERE username <> 'anxo'")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_confirmation_grandfathered")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("email_confirmation_grandfathered", sa.Boolean(), nullable=False, server_default="false")
        )
    # Lossy: the pre-migration set of confirmed vs. grandfathered-only
    # accounts isn't reconstructable, so this only restores the column.
