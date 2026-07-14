"""sync postgres native enum values with models

Revision ID: 148493887b66
Revises: a7c3f9e1b204
Create Date: 2026-07-09 13:58:36.800860

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "148493887b66"
down_revision: str | Sequence[str] | None = "a7c3f9e1b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add enum members that exist on the Python models but were never added to
    Postgres's native enum types (SQLite has no native enum, so this drift was
    invisible there). No-op on SQLite.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TYPE mediatype ADD VALUE IF NOT EXISTS 'book'")
    op.execute("ALTER TYPE watchstatus ADD VALUE IF NOT EXISTS 'paused'")


def downgrade() -> None:
    """Postgres has no ALTER TYPE ... DROP VALUE; not reversible."""
    pass
