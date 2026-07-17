#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 18:08:59.456452
"""

"""add per-task interval_minutes to periodic_task_runs

Revision ID: b7c3f5a91d02
Revises: a4e8d0c62f17
Create Date: 2026-07-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3f5a91d02"
down_revision: str | Sequence[str] | None = "a4e8d0c62f17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("periodic_task_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("periodic_task_runs", schema=None) as batch_op:
        batch_op.drop_column("interval_minutes")
