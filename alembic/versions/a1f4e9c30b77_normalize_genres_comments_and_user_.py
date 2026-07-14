"""normalize genres, comments and user usage counters

Genres: titles.genres held a comma-separated string (a 1NF violation); it
becomes a genres table + title_genres association.

Comments: comments duplicated the Title identity columns (media_type,
tmdb_id, title_key) instead of referencing the titles table; they get a
title_id FK. Comments whose target Title does not exist yet (possible for
threads on never-tracked titles) get one created from the comment's
identity, using the normalized key as the display title (best available).

Users: login_count / last_login_at / request_count were exact duplicates of
what login_events and request_days already record row-by-row; dropped.
Note: logins that happened before the login_events table existed are not in
it, so derived counts can be lower than the dropped column by that amount.

Revision ID: a1f4e9c30b77
Revises: 148493887b66
Create Date: 2026-07-10 00:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1f4e9c30b77"
down_revision: str | Sequence[str] | None = "148493887b66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEDIATYPE = postgresql.ENUM("film", "tv_show", "youtube", "book", name="mediatype", create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # ---------- 1. genres: comma-separated string -> association table ----------
    op.create_table(
        "genres",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("genres", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_genres_name"), ["name"], unique=True)
    op.create_table(
        "title_genres",
        sa.Column("title_id", sa.Integer(), nullable=False),
        sa.Column("genre_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"]),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("title_id", "genre_id"),
    )

    bind.execute(
        sa.text(
            """
        INSERT INTO genres (name)
        SELECT DISTINCT left(btrim(g), 100)
        FROM titles, unnest(string_to_array(genres, ',')) AS g
        WHERE genres IS NOT NULL AND btrim(g) <> ''
        """
        )
    )
    bind.execute(
        sa.text(
            """
        INSERT INTO title_genres (title_id, genre_id)
        SELECT DISTINCT t.id, ge.id
        FROM titles t,
             unnest(string_to_array(t.genres, ',')) AS g
             JOIN genres ge ON ge.name = left(btrim(g), 100)
        WHERE t.genres IS NOT NULL AND btrim(g) <> ''
        """
        )
    )

    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.drop_column("genres")

    # ---------- 2. comments: duplicated title identity -> title_id FK ----------
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("title_id", sa.Integer(), nullable=True))

    # Titles for comment threads nobody has tracked yet (identity exists only
    # on the comment). The normalized key is the best available display title.
    bind.execute(
        sa.text(
            """
        INSERT INTO titles (media_type, tmdb_id, title_key, title, created_at, updated_at)
        SELECT DISTINCT c.media_type, c.tmdb_id, c.title_key,
               COALESCE(c.title_key, 'tmdb #' || c.tmdb_id), now(), now()
        FROM comments c
        LEFT JOIN titles t
          ON t.media_type = c.media_type
         AND ((c.tmdb_id IS NOT NULL AND t.tmdb_id = c.tmdb_id)
           OR (c.tmdb_id IS NULL AND t.tmdb_id IS NULL AND t.title_key = c.title_key))
        WHERE t.id IS NULL
        """
        )
    )
    bind.execute(
        sa.text(
            """
        UPDATE comments c
        SET title_id = t.id
        FROM titles t
        WHERE t.media_type = c.media_type
          AND ((c.tmdb_id IS NOT NULL AND t.tmdb_id = c.tmdb_id)
            OR (c.tmdb_id IS NULL AND t.tmdb_id IS NULL AND t.title_key = c.title_key))
        """
        )
    )
    unresolved = bind.execute(sa.text("SELECT count(*) FROM comments WHERE title_id IS NULL")).scalar()
    if unresolved:
        raise RuntimeError(f"{unresolved} comments could not be linked to a title; aborting migration")

    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.alter_column("title_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_comments_title_id_titles", "titles", ["title_id"], ["id"])
        batch_op.create_index("ix_comment_target", ["title_id", "season", "episode"], unique=False)
        batch_op.drop_index(batch_op.f("ix_comments_tmdb_id"))
        batch_op.drop_index(batch_op.f("ix_comments_title_key"))
        batch_op.drop_column("media_type")
        batch_op.drop_column("tmdb_id")
        batch_op.drop_column("title_key")

    # ---------- 3. users: drop counters derivable from login_events / request_days ----------
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("login_count")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("request_count")


def downgrade() -> None:
    """Downgrade schema.

    Best-effort: the users counters are recomputed from login_events /
    request_days, so logins that predated the login_events table (already
    unrecoverable on upgrade) stay lost, and request_count comes back on the
    middleware's counting basis rather than the old per-authenticated-call one.
    """
    bind = op.get_bind()

    # ---------- 3. users counters ----------
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("login_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("request_count", sa.Integer(), nullable=True))
    bind.execute(
        sa.text(
            """
        UPDATE users u SET
          login_count = COALESCE(le.n, 0),
          last_login_at = le.latest,
          request_count = COALESCE(rd.total, 0)
        FROM users u2
        LEFT JOIN (SELECT user_id, count(*) AS n, max(created_at) AS latest
                   FROM login_events GROUP BY user_id) le ON le.user_id = u2.id
        LEFT JOIN (SELECT user_id, sum(count) AS total
                   FROM request_days GROUP BY user_id) rd ON rd.user_id = u2.id
        WHERE u.id = u2.id
        """
        )
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("login_count", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("request_count", existing_type=sa.Integer(), nullable=False)

    # ---------- 2. comments ----------
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("media_type", _MEDIATYPE, nullable=True))
        batch_op.add_column(sa.Column("tmdb_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("title_key", sa.String(length=300), nullable=True))
    bind.execute(
        sa.text(
            """
        UPDATE comments c
        SET media_type = t.media_type, tmdb_id = t.tmdb_id, title_key = t.title_key
        FROM titles t
        WHERE t.id = c.title_id
        """
        )
    )
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.alter_column("media_type", existing_type=_MEDIATYPE, nullable=False)
        batch_op.create_index(batch_op.f("ix_comments_tmdb_id"), ["tmdb_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_comments_title_key"), ["title_key"], unique=False)
        batch_op.drop_index("ix_comment_target")
        batch_op.drop_constraint("fk_comments_title_id_titles", type_="foreignkey")
        batch_op.drop_column("title_id")

    # ---------- 1. genres ----------
    with op.batch_alter_table("titles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("genres", sa.String(length=300), nullable=True))
    bind.execute(
        sa.text(
            """
        UPDATE titles t
        SET genres = sub.joined
        FROM (SELECT tg.title_id, left(string_agg(g.name, ', ' ORDER BY g.name), 300) AS joined
              FROM title_genres tg JOIN genres g ON g.id = tg.genre_id
              GROUP BY tg.title_id) sub
        WHERE sub.title_id = t.id
        """
        )
    )
    op.drop_table("title_genres")
    with op.batch_alter_table("genres", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_genres_name"))
    op.drop_table("genres")
