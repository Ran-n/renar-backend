"""split media_items into titles (shared catalog) and per-user entries

Revision ID: c3a9f1d7e824
Revises: 2b07a12077a1
Create Date: 2026-07-08 00:00:00.000001

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a9f1d7e824'
down_revision: Union[str, Sequence[str], None] = '2b07a12077a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _title_key(title: str) -> str:
    return title.strip().casefold()


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # ---------- 1. create the shared "titles" catalog table ----------
    op.create_table(
        'titles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('media_type', sa.Enum('film', 'tv_show', 'youtube', 'book', name='mediatype'), nullable=False),
        sa.Column('tmdb_id', sa.Integer(), nullable=True),
        sa.Column('title_key', sa.String(length=300), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('poster_url', sa.String(length=500), nullable=True),
        sa.Column('runtime_minutes', sa.Integer(), nullable=True),
        sa.Column('total_episodes', sa.Integer(), nullable=True),
        sa.Column('genres', sa.String(length=300), nullable=True),
        sa.Column('author', sa.String(length=300), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('titles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_titles_media_type'), ['media_type'], unique=False)
        batch_op.create_index(
            'uq_title_tmdb', ['media_type', 'tmdb_id'], unique=True,
            sqlite_where=sa.column('tmdb_id').isnot(None),
            postgresql_where=sa.column('tmdb_id').isnot(None),
        )
        batch_op.create_index(
            'uq_title_key', ['media_type', 'title_key'], unique=True,
            sqlite_where=sa.column('tmdb_id').is_(None),
            postgresql_where=sa.column('tmdb_id').is_(None),
        )

    # ---------- 2. add a nullable title_id FK to media_items, to populate next ----------
    with op.batch_alter_table('media_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('title_id', sa.Integer(), nullable=True))

    # ---------- 3. backfill: one Title per distinct (media_type, tmdb_id) or
    #              (media_type, normalized title) group of existing media_items rows ----------
    md = sa.MetaData()
    titles_t = sa.Table(
        'titles',
        md,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('media_type', sa.String()),
        sa.Column('tmdb_id', sa.Integer()),
        sa.Column('title_key', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('year', sa.Integer()),
        sa.Column('poster_url', sa.String()),
        sa.Column('runtime_minutes', sa.Integer()),
        sa.Column('total_episodes', sa.Integer()),
        sa.Column('genres', sa.String()),
        sa.Column('author', sa.String()),
        sa.Column('page_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )
    media_items_t = sa.Table(
        'media_items',
        md,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('media_type', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('year', sa.Integer()),
        sa.Column('poster_url', sa.String()),
        sa.Column('tmdb_id', sa.Integer()),
        sa.Column('runtime_minutes', sa.Integer()),
        sa.Column('total_episodes', sa.Integer()),
        sa.Column('genres', sa.String()),
        sa.Column('author', sa.String()),
        sa.Column('page_count', sa.Integer()),
        sa.Column('title_id', sa.Integer()),
    )

    rows = bind.execute(sa.select(media_items_t)).fetchall()
    now = datetime.now(UTC)
    group_to_title_id: dict[tuple, int] = {}
    for row in rows:
        key = (
            (row.media_type, row.tmdb_id)
            if row.tmdb_id is not None
            else (row.media_type, _title_key(row.title))
        )
        title_id = group_to_title_id.get(key)
        if title_id is None:
            result = bind.execute(
                titles_t.insert().values(
                    media_type=row.media_type,
                    tmdb_id=row.tmdb_id,
                    title_key=None if row.tmdb_id is not None else _title_key(row.title),
                    title=row.title,
                    year=row.year,
                    poster_url=row.poster_url,
                    runtime_minutes=row.runtime_minutes,
                    total_episodes=row.total_episodes,
                    genres=row.genres,
                    author=row.author,
                    page_count=row.page_count,
                    created_at=now,
                    updated_at=now,
                )
            )
            title_id = result.inserted_primary_key[0]
            group_to_title_id[key] = title_id
        bind.execute(
            media_items_t.update().where(media_items_t.c.id == row.id).values(title_id=title_id)
        )

    # ---------- 4. lock down title_id, drop the now-redundant columns, swap the unique constraint ----------
    with op.batch_alter_table('media_items', schema=None) as batch_op:
        batch_op.alter_column('title_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_media_items_title_id_titles', 'titles', ['title_id'], ['id'])
        batch_op.create_index(batch_op.f('ix_media_items_title_id'), ['title_id'], unique=False)
        batch_op.drop_constraint('uq_user_media_title', type_='unique')
        batch_op.drop_constraint('uq_user_media_tmdb', type_='unique')
        batch_op.create_unique_constraint('uq_user_title', ['user_id', 'title_id'])
        batch_op.drop_index(batch_op.f('ix_media_items_media_type'))
        batch_op.drop_column('title')
        batch_op.drop_column('year')
        batch_op.drop_column('poster_url')
        batch_op.drop_column('tmdb_id')
        batch_op.drop_column('runtime_minutes')
        batch_op.drop_column('total_episodes')
        batch_op.drop_column('genres')
        batch_op.drop_column('author')
        batch_op.drop_column('page_count')
        batch_op.drop_column('media_type')


def downgrade() -> None:
    """Downgrade schema.

    Best-effort: restores the media_items columns and copies each row's Title
    data back onto it, but two library entries that had pointed at the same
    shared Title (i.e. two different users tracking the same movie) will end
    up with independently-editable duplicate title text again, exactly as
    before this migration existed.
    """
    bind = op.get_bind()

    with op.batch_alter_table('media_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('media_type', sa.Enum('film', 'tv_show', 'youtube', 'book', name='mediatype'), nullable=True))
        batch_op.add_column(sa.Column('title', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('year', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('poster_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('tmdb_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('runtime_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('total_episodes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('genres', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('author', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('page_count', sa.Integer(), nullable=True))

    media_items_t = sa.table(
        'media_items',
        sa.column('id', sa.Integer()),
        sa.column('title_id', sa.Integer()),
        sa.column('media_type', sa.String()),
        sa.column('title', sa.String()),
        sa.column('year', sa.Integer()),
        sa.column('poster_url', sa.String()),
        sa.column('tmdb_id', sa.Integer()),
        sa.column('runtime_minutes', sa.Integer()),
        sa.column('total_episodes', sa.Integer()),
        sa.column('genres', sa.String()),
        sa.column('author', sa.String()),
        sa.column('page_count', sa.Integer()),
    )
    titles_t = sa.table(
        'titles',
        sa.column('id', sa.Integer()),
        sa.column('media_type', sa.String()),
        sa.column('title', sa.String()),
        sa.column('year', sa.Integer()),
        sa.column('poster_url', sa.String()),
        sa.column('tmdb_id', sa.Integer()),
        sa.column('runtime_minutes', sa.Integer()),
        sa.column('total_episodes', sa.Integer()),
        sa.column('genres', sa.String()),
        sa.column('author', sa.String()),
        sa.column('page_count', sa.Integer()),
    )

    joined = sa.select(
        media_items_t.c.id,
        titles_t.c.media_type,
        titles_t.c.title,
        titles_t.c.year,
        titles_t.c.poster_url,
        titles_t.c.tmdb_id,
        titles_t.c.runtime_minutes,
        titles_t.c.total_episodes,
        titles_t.c.genres,
        titles_t.c.author,
        titles_t.c.page_count,
    ).select_from(media_items_t.join(titles_t, media_items_t.c.title_id == titles_t.c.id))

    for row in bind.execute(joined).fetchall():
        bind.execute(
            media_items_t.update().where(media_items_t.c.id == row.id).values(
                media_type=row.media_type,
                title=row.title,
                year=row.year,
                poster_url=row.poster_url,
                tmdb_id=row.tmdb_id,
                runtime_minutes=row.runtime_minutes,
                total_episodes=row.total_episodes,
                genres=row.genres,
                author=row.author,
                page_count=row.page_count,
            )
        )

    with op.batch_alter_table('media_items', schema=None) as batch_op:
        batch_op.alter_column('media_type', existing_type=sa.Enum('film', 'tv_show', 'youtube', 'book', name='mediatype'), nullable=False)
        batch_op.alter_column('title', existing_type=sa.String(length=300), nullable=False)
        batch_op.create_index(batch_op.f('ix_media_items_media_type'), ['media_type'], unique=False)
        batch_op.drop_constraint('uq_user_title', type_='unique')
        batch_op.create_unique_constraint('uq_user_media_title', ['user_id', 'media_type', 'title'])
        batch_op.create_unique_constraint('uq_user_media_tmdb', ['user_id', 'media_type', 'tmdb_id'])
        batch_op.drop_constraint('fk_media_items_title_id_titles', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_media_items_title_id'))
        batch_op.drop_column('title_id')

    with op.batch_alter_table('titles', schema=None) as batch_op:
        batch_op.drop_index('uq_title_key')
        batch_op.drop_index('uq_title_tmdb')
        batch_op.drop_index(batch_op.f('ix_titles_media_type'))

    op.drop_table('titles')
