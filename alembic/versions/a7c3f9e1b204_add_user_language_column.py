"""add user language column

Revision ID: a7c3f9e1b204
Revises: c2d5e83f1a67
Create Date: 2026-07-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c3f9e1b204"
down_revision: Union[str, Sequence[str], None] = "c2d5e83f1a67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("language", sa.String(length=10), nullable=False, server_default="en"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("language")
