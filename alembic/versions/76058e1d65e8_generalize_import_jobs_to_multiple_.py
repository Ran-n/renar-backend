#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/27 00:00:00.000000
Revised: 2026/07/27 00:00:00.000000
"""

"""generalize import_jobs to multiple import origins

The import system is moving from one hardcoded origin (TV Time) to a
registry of importers dispatched by auto-detecting the uploaded file's
format (routers/imports.py) — a Renar export (.7z) today, more origins
(e.g. Letterboxd) later. import_jobs (each origin's durable "did my last
import finish, and how" marker, since live progress is only tracked
in-memory) needs a `kind` column and a composite (user_id, kind) primary
key so an account can hold one outcome row per origin instead of clobbering
itself the moment it has import history from more than one.

Existing rows are backfilled to kind='tvtime' — the only origin this table
ever recorded before now.

Revision ID: 76058e1d65e8
Revises: c1d4e7f2a9b6
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "76058e1d65e8"
down_revision: str | Sequence[str] | None = "c1d4e7f2a9b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("import_jobs", sa.Column("kind", sa.String(30), nullable=False, server_default="tvtime"))
    op.drop_constraint("import_jobs_pkey", "import_jobs", type_="primary")
    op.create_primary_key("import_jobs_pkey", "import_jobs", ["user_id", "kind"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("import_jobs_pkey", "import_jobs", type_="primary")
    op.create_primary_key("import_jobs_pkey", "import_jobs", ["user_id"])
    op.drop_column("import_jobs", "kind")
