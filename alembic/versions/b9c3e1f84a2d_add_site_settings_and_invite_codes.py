#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 09:41:27.981824
Revised: 2026/07/17 09:41:27.981824
"""

"""add site_settings and invite_codes tables

Revision ID: b9c3e1f84a2d
Revises: a7c2e9f4b816
Create Date: 2026-07-16 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c3e1f84a2d"
down_revision: str | Sequence[str] | None = "a7c2e9f4b816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invite_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("registration_open", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("auth_rate_limit_per_minute", sa.Integer(), nullable=False),
        sa.Column("register_per_hour_per_ip", sa.Integer(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False),
        sa.Column("flood_ban_per_minute", sa.Integer(), nullable=False),
        sa.Column("login_backoff_threshold", sa.Integer(), nullable=False),
        sa.Column("login_backoff_account_threshold", sa.Integer(), nullable=False),
        sa.Column("login_backoff_minutes", sa.Integer(), nullable=False),
        sa.Column("probe_ban_threshold", sa.Integer(), nullable=False),
        sa.Column("probe_window_minutes", sa.Integer(), nullable=False),
        sa.Column("ban_minutes", sa.Integer(), nullable=False),
        sa.Column("strike_ban_threshold", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_site_settings_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_invite_codes_code"), ["code"], unique=True)
        batch_op.create_index(batch_op.f("ix_invite_codes_created_by_user_id"), ["created_by_user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_invite_codes_created_by_user_id"))
        batch_op.drop_index(batch_op.f("ix_invite_codes_code"))

    op.drop_table("invite_codes")
    op.drop_table("site_settings")
