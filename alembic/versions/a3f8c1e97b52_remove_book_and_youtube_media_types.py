#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/18 18:30:00.000000
Revised: 2026/07/18 18:30:00.000000
"""

"""remove book and youtube media types

Revision ID: a3f8c1e97b52
Revises: 2267d348213e
Create Date: 2026-07-18 18:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f8c1e97b52"
down_revision: str | Sequence[str] | None = "2267d348213e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retire the book/youtube media types (feature removed, scope narrowed
    to film/tv_show).

    Deletes the library entries and title rows still using either type —
    checked by hand against the live DB before writing this migration: 2
    completed book entries (user 1's "El capitán Alatriste", user 2's
    "Metamorphosis") and 3 orphaned youtube titles with no library entries.
    None of the five had comments/tmdb_cache/title_genres/episode_watches/
    notifications/watch_events/episode_custom_stills rows referencing them,
    so no further cascade is needed.

    Postgres has no `ALTER TYPE ... DROP VALUE`, so the enum is recreated
    without the retired values and the one column using it is repointed.
    """
    op.execute(
        "DELETE FROM media_items WHERE title_id IN (SELECT id FROM titles WHERE media_type IN ('book', 'youtube'))"
    )
    op.execute("DELETE FROM titles WHERE media_type IN ('book', 'youtube')")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE mediatype RENAME TO mediatype_old")
        op.execute("CREATE TYPE mediatype AS ENUM ('film', 'tv_show')")
        op.execute("ALTER TABLE titles ALTER COLUMN media_type TYPE mediatype USING media_type::text::mediatype")
        op.execute("DROP TYPE mediatype_old")

    with op.batch_alter_table("titles") as batch_op:
        batch_op.drop_column("page_count")
        batch_op.drop_column("author")


def downgrade() -> None:
    """Not reversible: the enum values and deleted rows are gone."""
    pass
