#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 12:20:00.000000
Revised: 2026/11/09 11:49:58.976079
"""

"""add email confirmation

Adds users.email_confirmed / users.pending_email and the
email_confirmation_codes table (see users/email_confirmation.py) for the
registration/email-change confirmation-code flow — closes the ranking-
exploit gap where unconfirmed, hand-registered throwaway accounts could pad
/stats/ranking's percentile denominator and "ahead of me" comparison.

No backfill: every existing user starts email_confirmed=False and has to
re-confirm, same as a brand-new signup (deliberate — see TODO.md's
"Real email confirmation on registration" entry). That also means
app_counters.total_users (previously "all users", now "confirmed users
only" — see db_triggers.py) drops to 0 immediately after this migration;
the trigger SQL is re-executed here (CREATE OR REPLACE, safe to rerun) and
the counter is explicitly reset to match, since the existing app_counters
row means the trigger's own seed INSERT (ON CONFLICT DO NOTHING) is a no-op.

Revision ID: ee151fb9d02c
Revises: a1f5e8c3d629
Create Date: 2026-07-20 12:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from renar_backend.db_triggers import USER_COUNT_TRIGGER_SQL

# revision identifiers, used by Alembic.
revision: str = "ee151fb9d02c"
down_revision: str | Sequence[str] | None = "a1f5e8c3d629"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Pre-this-migration trigger: total_users counted every user, not just
# confirmed ones. Inlined here (not imported — db_triggers.py now only holds
# the current version) so downgrade() can restore exactly what upgrade()
# replaced.
_OLD_USER_COUNT_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION trg_users_count() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE app_counters SET total_users = total_users + 1 WHERE id = 1;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE app_counters SET total_users = total_users - 1 WHERE id = 1;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_count_iud ON users;
CREATE TRIGGER users_count_iud
AFTER INSERT OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION trg_users_count();
"""


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email_confirmed", sa.Boolean(), nullable=False, server_default="false"))
        batch_op.add_column(sa.Column("pending_email", sa.String(length=255), nullable=True))
    op.create_index("ix_users_email_confirmed", "users", ["email_confirmed"])

    op.create_table(
        "email_confirmation_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_confirmation_codes_user_id", "email_confirmation_codes", ["user_id"])

    # Replaces trg_users_count (INSERT/DELETE) with the confirmed-only
    # version and adds trg_users_email_confirmed (UPDATE) — see db_triggers.py.
    op.execute(USER_COUNT_TRIGGER_SQL)
    # The seed INSERT inside USER_COUNT_TRIGGER_SQL is ON CONFLICT DO NOTHING
    # and app_counters already has its id=1 row from a prior migration, so the
    # counter still holds the old "all users" total until reset explicitly.
    op.execute("UPDATE app_counters SET total_users = (SELECT COUNT(*) FROM users WHERE email_confirmed) WHERE id = 1")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS users_email_confirmed_update ON users")
    op.execute("DROP FUNCTION IF EXISTS trg_users_email_confirmed()")
    op.execute(_OLD_USER_COUNT_TRIGGER_SQL)
    op.execute("UPDATE app_counters SET total_users = (SELECT COUNT(*) FROM users) WHERE id = 1")

    op.drop_index("ix_email_confirmation_codes_user_id", table_name="email_confirmation_codes")
    op.drop_table("email_confirmation_codes")

    op.drop_index("ix_users_email_confirmed", table_name="users")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("pending_email")
        batch_op.drop_column("email_confirmed")
