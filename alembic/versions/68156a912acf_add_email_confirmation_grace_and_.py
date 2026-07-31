"""add email confirmation grace and cleanup days to site settings

Revision ID: 68156a912acf
Revises: 4b2026dc80cd
Create Date: 2026-07-29 13:51:03.521812

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "68156a912acf"
down_revision: str | Sequence[str] | None = "4b2026dc80cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "site_settings",
        sa.Column("email_confirmation_grace_days", sa.Integer(), nullable=False, server_default="7"),
    )
    op.add_column(
        "site_settings",
        sa.Column("unconfirmed_account_cleanup_days", sa.Integer(), nullable=False, server_default="14"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("site_settings", "unconfirmed_account_cleanup_days")
    op.drop_column("site_settings", "email_confirmation_grace_days")
