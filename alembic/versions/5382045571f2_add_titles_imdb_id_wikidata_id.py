#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000
"""

"""add titles.imdb_id, titles.wikidata_id

Cross-reference ids from TMDB's external_ids, cached on the shared Title
row so other integrations don't need their own title-matching step: OMDb
ratings lookup (imdb_id) and Wikipedia sitelinks (wikidata_id). Neither is
an identity source like tmdb_id/tvdb_id — no unique index.

Revision ID: 5382045571f2
Revises: 1f4b8d2c6a91
Create Date: 2026-08-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5382045571f2"
down_revision: str | Sequence[str] | None = "1f4b8d2c6a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("imdb_id", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("wikidata_id", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.drop_column("wikidata_id")
        batch_op.drop_column("imdb_id")
