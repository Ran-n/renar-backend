#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 11:44:20.171407
Revised: 2026/08/24 12:38:50.773578
"""

"""add lists, reviews, deletion grace period, username cooldown

Revision ID: 88137cd72bc2
Revises: a8f3c2e1d9b5
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "88137cd72bc2"
down_revision: str | Sequence[str] | None = "a8f3c2e1d9b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_users_deletion_requested_at", ["deletion_requested_at"], unique=False)

    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("username_cooldown_days", sa.Integer(), nullable=False, server_default="30"))
        batch_op.add_column(sa.Column("deletion_grace_days", sa.Integer(), nullable=False, server_default="30"))

    op.create_table(
        "released_usernames",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("released_usernames", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_released_usernames_username"), ["username"], unique=False)
        batch_op.create_index(batch_op.f("ix_released_usernames_released_at"), ["released_at"], unique=False)

    op.create_table(
        "lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_lists_user_id"), ["user_id"], unique=False)

    op.create_table(
        "list_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("title_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["list_id"], ["lists.id"]),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_id", "title_id", name="uq_list_item"),
    )
    with op.batch_alter_table("list_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_list_items_list_id"), ["list_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_list_items_title_id"), ["title_id"], unique=False)

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "title_id", name="uq_review_user_title"),
    )
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reviews_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_reviews_title_id"), ["title_id"], unique=False)

    op.create_table(
        "review_whitelist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_review_whitelist_user_id"),
    )
    with op.batch_alter_table("review_whitelist", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_review_whitelist_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("review_whitelist")
    op.drop_table("reviews")
    op.drop_table("list_items")
    op.drop_table("lists")
    op.drop_table("released_usernames")

    with op.batch_alter_table("site_settings", schema=None) as batch_op:
        batch_op.drop_column("deletion_grace_days")
        batch_op.drop_column("username_cooldown_days")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_deletion_requested_at")
        batch_op.drop_column("deletion_requested_at")
