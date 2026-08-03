#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/02 18:21:39.711212
Revised: 2026/08/02 18:21:39.711212
"""

"""drop custom themes

Custom themes moved frontend-only (a locally-saved SharedPreferences list,
see renar_frontend/branding/themes.py) — no cross-device sync, no server
storage. This reverses a1c9e4f7b3d2/aa0b78014ee0 in full.

Revision ID: 02638e4154de
Revises: aa0b78014ee0
Create Date: 2026-08-02 18:21:39.711212

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "02638e4154de"
down_revision: str | Sequence[str] | None = "aa0b78014ee0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("premium_custom_themes_enabled")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_users_custom_theme_id_custom_themes", type_="foreignkey")
        batch_op.drop_column("custom_theme_id")
    op.drop_index(op.f("ix_custom_themes_user_id"), table_name="custom_themes")
    op.drop_table("custom_themes")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "custom_themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=5), nullable=False),
        sa.Column("seed_color", sa.String(length=7), nullable=False),
        sa.Column("accents", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("theme_colors", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_custom_themes_user_id"), "custom_themes", ["user_id"], unique=False)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("custom_theme_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_custom_theme_id_custom_themes", "custom_themes", ["custom_theme_id"], ["id"], ondelete="SET NULL"
        )
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("premium_custom_themes_enabled", sa.Boolean(), server_default="true", nullable=False)
        )
