"""add comment replies and reports

Replies: comments gain a self-referential parent_id, so any comment can be
answered (arbitrary depth). Existing comments are all top-level (NULL).

Reports: new comment_reports table, one row per (comment, reporter), with an
optional free-text reason. Surfaced in the admin comment manager.

Revision ID: 9c4e2d81f5a3
Revises: a1f4e9c30b77
Create Date: 2026-07-10 12:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4e2d81f5a3"
down_revision: str | Sequence[str] | None = "a1f4e9c30b77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("comments", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_comments_parent_id"), "comments", ["parent_id"], unique=False)
    op.create_foreign_key("fk_comments_parent_id_comments", "comments", "comments", ["parent_id"], ["id"])

    op.create_table(
        "comment_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comment_id", "user_id", name="uq_comment_report"),
    )
    with op.batch_alter_table("comment_reports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_comment_reports_comment_id"), ["comment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_comment_reports_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("comment_reports")
    op.drop_constraint("fk_comments_parent_id_comments", "comments", type_="foreignkey")
    op.drop_index(op.f("ix_comments_parent_id"), table_name="comments")
    op.drop_column("comments", "parent_id")
