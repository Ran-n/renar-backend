#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:03.604242
Revised: 2026/11/22 03:03:52.281412
"""

"""add moderation_decisions

One row per moderation decision and its statement of reasons (DSA art. 17),
written for every moderation action in the admin panel and deleted 6 months
after the measure ends.

Revision ID: e8f2b5d1a7c4
Revises: d7e1a4c9f2b3
Create Date: 2026-11-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8f2b5d1a7c4"
down_revision: str | Sequence[str] | None = "d7e1a4c9f2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIONS = (
    "comment_removed",
    "review_removed",
    "account_suspended",
    "account_closed",
    "username_reset",
    "review_rights_withdrawn",
    "comment_report_dismissed",
    "review_report_dismissed",
)
_REASONS = (
    "illegal_content",
    "no_rights",
    "harassment",
    "hate_or_violence",
    "child_sexual_content",
    "spam",
    "circumvention",
    "scraping",
    "disruption",
    "no_breach",
)
_MAIL = ("pending", "sent", "failed", "not_configured", "not_needed")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "moderation_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.Enum(*_ACTIONS, name="moderationaction"), nullable=False),
        sa.Column("reason", sa.Enum(*_REASONS, name="moderationreason"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("moderator", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("from_report", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measure_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.Enum(*_MAIL, name="mailstatus"), nullable=False),
        sa.Column("reporters_notified", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_decisions_user_id", "moderation_decisions", ["user_id"])
    op.create_index("ix_moderation_decisions_created_at", "moderation_decisions", ["created_at"])
    op.create_index("ix_moderation_decisions_measure_ended_at", "moderation_decisions", ["measure_ended_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("moderation_decisions")
    for name in ("moderationaction", "moderationreason", "mailstatus"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
