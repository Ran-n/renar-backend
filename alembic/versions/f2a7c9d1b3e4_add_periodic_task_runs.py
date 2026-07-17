#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 14:51:05.811584
"""

"""add periodic_task_runs table

Revision ID: f2a7c9d1b3e4
Revises: 23dd41789cea
Create Date: 2026-07-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a7c9d1b3e4"
down_revision: str | Sequence[str] | None = "23dd41789cea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "periodic_task_runs",
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status", sa.String(), nullable=False),
        sa.Column("last_detail", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("task_key"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("periodic_task_runs")
