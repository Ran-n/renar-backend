#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 00:00:00.000000
Revised: 2026/07/21 09:51:06.741193
"""

"""add import_jobs table

routers/imports.py's TV Time import tracks live progress in an in-memory
`_progress` dict on a daemon thread. That's fine for normal polling, but a
server restart mid-import loses the job entirely — and GET
/import/tvtime/status then falls back to its "Never run" default (finished
True, no error), which the frontend renders as a false "Import complete ✓"
with all-zero counts instead of surfacing the interruption.

import_jobs is a durable, per-user marker of the last import's *outcome*,
written only at job start (finished=False) and at completion/failure
(finished=True, error/summary set) — not on every progress tick, so it
doesn't become a write-heavy progress log. A status poll that finds nothing
in the in-memory dict (new process after a restart) falls back to this row:
finished=False there means the job was in flight when the process died, so
the endpoint can now say so instead of pretending nothing happened.

Revision ID: b2f7a6d391ea
Revises: ffffe2b24717
Create Date: 2026-07-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2f7a6d391ea"
down_revision: str | Sequence[str] | None = "ffffe2b24717"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "import_jobs",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("import_jobs")
