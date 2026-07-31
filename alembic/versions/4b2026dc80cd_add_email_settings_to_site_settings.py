"""add email settings to site settings

Revision ID: 4b2026dc80cd
Revises: 40c05acfeddb
Create Date: 2026-07-29 13:31:40.780492

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b2026dc80cd"
down_revision: str | Sequence[str] | None = "40c05acfeddb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "site_settings",
        sa.Column("email_sender_address", sa.String(), nullable=False, server_default="noreply@renar.app"),
    )
    op.add_column("site_settings", sa.Column("email_sender_name", sa.String(), nullable=False, server_default="Renar"))
    op.add_column(
        "site_settings",
        sa.Column("confirmation_code_ttl_minutes", sa.Integer(), nullable=False, server_default="15"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("site_settings", "confirmation_code_ttl_minutes")
    op.drop_column("site_settings", "email_sender_name")
    op.drop_column("site_settings", "email_sender_address")
