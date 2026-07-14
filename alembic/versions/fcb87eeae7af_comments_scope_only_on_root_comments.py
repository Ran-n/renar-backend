"""comments: title_id/season/episode only on root comments (BCNF)

A reply's title_id/season/episode used to be copied from its parent so
every row in a thread answered the same target query. That's a transitive
dependency through parent_id (BCNF violation): a reply's scope is a fact
about its thread root, not independent data about the reply itself. Only
root comments (parent_id IS NULL) keep it now; replies derive it by
walking parent_id up to the root (see comment_threads.resolve_root_scope).

Revision ID: fcb87eeae7af
Revises: e79fbd00fa50
Create Date: 2026-07-12 20:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fcb87eeae7af"
down_revision: str | Sequence[str] | None = "f3c1a2b9e045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("comments", "title_id", nullable=True)
    op.execute("UPDATE comments SET title_id = NULL, season = NULL, episode = NULL WHERE parent_id IS NOT NULL")


def downgrade() -> None:
    # Restore each reply's scope from its thread root (reverses the upgrade's
    # backfill) before reinstating NOT NULL.
    op.execute(
        """
        WITH RECURSIVE ancestry AS (
            SELECT id, id AS reply_id, parent_id, title_id, season, episode FROM comments
            UNION ALL
            SELECT c.id, a.reply_id, c.parent_id, c.title_id, c.season, c.episode
            FROM comments c
            JOIN ancestry a ON c.id = a.parent_id
        )
        UPDATE comments
        SET title_id = ancestry.title_id, season = ancestry.season, episode = ancestry.episode
        FROM ancestry
        WHERE comments.id = ancestry.reply_id
          AND comments.title_id IS NULL
          AND ancestry.title_id IS NOT NULL
        """
    )
    op.alter_column("comments", "title_id", nullable=False)
