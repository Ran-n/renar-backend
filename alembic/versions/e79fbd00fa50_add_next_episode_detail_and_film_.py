"""add next-episode detail and film release_date columns to titles

/upcoming previously did one live TMDB fetch per tracked title on every
request, which took over a minute for large libraries. These columns let
it read already-synced data straight off the titles row instead: TV
next-episode season/number/name (next_episode_air_date already existed)
kept fresh by the notifier's periodic show poll, and film release_date
kept fresh by a new periodic want-to-watch film poll.

Revision ID: e79fbd00fa50
Revises: d9e6b3a71f42
Create Date: 2026-07-12 18:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e79fbd00fa50"
down_revision: str | Sequence[str] | None = "d9e6b3a71f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("titles", sa.Column("next_episode_season", sa.Integer(), nullable=True))
    op.add_column("titles", sa.Column("next_episode_number", sa.Integer(), nullable=True))
    op.add_column("titles", sa.Column("next_episode_name", sa.String(length=300), nullable=True))
    op.add_column("titles", sa.Column("release_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("titles", "release_date")
    op.drop_column("titles", "next_episode_name")
    op.drop_column("titles", "next_episode_number")
    op.drop_column("titles", "next_episode_season")
