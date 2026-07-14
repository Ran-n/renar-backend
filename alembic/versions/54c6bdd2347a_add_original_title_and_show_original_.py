#!/usr/bin/env python3
"""add original_title and show_original_titles

Authors: Ran# <ran.hash@proton.me>

Library titles were frozen to whatever language first added them, since
titles.title is a single shared string. This adds titles.original_title
(TMDB's language-independent original_title/original_name) and
users.show_original_titles, an opt-in to always display it instead of the
per-user localized display_title that list_media now derives from cached
TMDB translations.

Revision ID: 54c6bdd2347a
Revises: c5a8d2e13f6b
Create Date: 2026-07-14 00:00:00.000002

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "54c6bdd2347a"
down_revision: str | Sequence[str] | None = "c5a8d2e13f6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("titles", sa.Column("original_title", sa.String(length=300), nullable=True))
    op.add_column(
        "users",
        sa.Column("show_original_titles", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "show_original_titles")
    op.drop_column("titles", "original_title")
