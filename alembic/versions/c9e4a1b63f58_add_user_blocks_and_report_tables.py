#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:19:57.472555
Revised: 2026/11/15 02:45:14.090010
"""

"""add user_blocks, user_reports and review_reports tables

user_blocks: one row per (blocker, blocked); the effect is symmetric but
only the blocker may undo it. user_reports / review_reports: one row per
(target, reporter), the same shape as comment_reports.

Revision ID: c9e4a1b63f58
Revises: b8d3f0a52e47
Create Date: 2026-11-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e4a1b63f58"
down_revision: str | Sequence[str] | None = "b8d3f0a52e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blocker_id", sa.Integer(), nullable=False),
        sa.Column("blocked_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_user_block_not_self"),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_block_pair"),
    )
    op.create_index(op.f("ix_user_blocks_blocker_id"), "user_blocks", ["blocker_id"], unique=False)
    op.create_index(op.f("ix_user_blocks_blocked_id"), "user_blocks", ["blocked_id"], unique=False)

    op.create_table(
        "user_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reported_user_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reported_user_id <> reporter_id", name="ck_user_report_not_self"),
        sa.ForeignKeyConstraint(["reported_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reported_user_id", "reporter_id", name="uq_user_report"),
    )
    op.create_index(op.f("ix_user_reports_reported_user_id"), "user_reports", ["reported_user_id"], unique=False)
    op.create_index(op.f("ix_user_reports_reporter_id"), "user_reports", ["reporter_id"], unique=False)

    op.create_table(
        "review_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "reporter_id", name="uq_review_report"),
    )
    op.create_index(op.f("ix_review_reports_review_id"), "review_reports", ["review_id"], unique=False)
    op.create_index(op.f("ix_review_reports_reporter_id"), "review_reports", ["reporter_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_review_reports_reporter_id"), table_name="review_reports")
    op.drop_index(op.f("ix_review_reports_review_id"), table_name="review_reports")
    op.drop_table("review_reports")
    op.drop_index(op.f("ix_user_reports_reporter_id"), table_name="user_reports")
    op.drop_index(op.f("ix_user_reports_reported_user_id"), table_name="user_reports")
    op.drop_table("user_reports")
    op.drop_index(op.f("ix_user_blocks_blocked_id"), table_name="user_blocks")
    op.drop_index(op.f("ix_user_blocks_blocker_id"), table_name="user_blocks")
    op.drop_table("user_blocks")
