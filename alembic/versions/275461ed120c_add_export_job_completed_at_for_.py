#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/27 15:54:17.996507
Revised: 2026/07/27 15:54:17.996507
"""

"""add export job completed_at for cooldown and expiry

Adds ExportJob.completed_at, set when a build finishes successfully
(users/export_queue.py::_run). Two things read it: routers/export.py's
POST /export/data rejects a re-request while a ready export is still
within EXPORT_EXPIRY_DAYS of its completed_at (the cooldown), and GET
/export/data/status stops reporting "ready" once that same window has
passed (the expiry) — export_queue.purge_expired_exports then deletes the
file and this row on a schedule so it doesn't just sit unreachable on disk.

Existing rows (finished=True, error IS NULL, i.e. already "ready" before
this migration) get completed_at backfilled to queued_at — an
approximation (the real completion time was never recorded), but a safe
one: it starts their cooldown/expiry clock now rather than leaving them
NULL, which purge_expired_exports would otherwise never match (excluded
from its NOT NULL filter) and which the status/request endpoints would
otherwise have to special-case as "unknown, treat as already expired" —
simpler to just give every pre-existing ready export a concrete, if
approximate, start time for the same 7-day window everyone else gets.

Revision ID: 275461ed120c
Revises: 76058e1d65e8
Create Date: 2026-07-27 15:53:53.653934

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "275461ed120c"
down_revision: str | Sequence[str] | None = "76058e1d65e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE export_jobs SET completed_at = queued_at WHERE finished = true AND error IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.drop_column("completed_at")
