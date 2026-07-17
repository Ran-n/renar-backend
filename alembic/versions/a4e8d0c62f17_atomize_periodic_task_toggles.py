#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 17:57:26.874615
"""

"""atomize periodic task toggles: per-task enable flag, drop grouped SiteSettings booleans

Revision ID: a4e8d0c62f17
Revises: f2a7c9d1b3e4
Create Date: 2026-07-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4e8d0c62f17"
down_revision: str | Sequence[str] | None = "f2a7c9d1b3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("periodic_task_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False))
        batch_op.alter_column("last_started_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column("last_finished_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column("last_status", existing_type=sa.String(), nullable=True)
        batch_op.alter_column("last_detail", existing_type=sa.Text(), server_default="", nullable=False)

    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("bans_check_enabled")
        batch_op.drop_column("film_check_enabled")
        batch_op.drop_column("episode_check_enabled")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("episode_check_enabled", sa.Boolean(), server_default="true", nullable=False))
        batch_op.add_column(sa.Column("film_check_enabled", sa.Boolean(), server_default="true", nullable=False))
        batch_op.add_column(sa.Column("bans_check_enabled", sa.Boolean(), server_default="true", nullable=False))

    with op.batch_alter_table("periodic_task_runs", schema=None) as batch_op:
        batch_op.alter_column("last_detail", existing_type=sa.Text(), server_default=None, nullable=False)
        batch_op.alter_column("last_status", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("last_finished_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column("last_started_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.drop_column("enabled")
