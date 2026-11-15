#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:42.867446
Revised: 2026/11/14 00:22:42.867446
"""

"""add review_likes table

Like/dislike reactions on reviews, the same shape as comment_likes: one row
per (review, user), value +1 or -1.

Revision ID: a7c2e9f41d36
Revises: d9b3f6a2c1e7
Create Date: 2026-11-13 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c2e9f41d36"
down_revision: str | Sequence[str] | None = "d9b3f6a2c1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_likes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_review_like_value"),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "user_id", name="uq_review_like"),
    )
    op.create_index(op.f("ix_review_likes_review_id"), "review_likes", ["review_id"], unique=False)
    op.create_index(op.f("ix_review_likes_user_id"), "review_likes", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_review_likes_user_id"), table_name="review_likes")
    op.drop_index(op.f("ix_review_likes_review_id"), table_name="review_likes")
    op.drop_table("review_likes")
