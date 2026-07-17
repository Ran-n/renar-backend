"""notification composite indexes

Revision ID: 45a9dba29ff9
Revises: 7bc87a340d08
Create Date: 2026-07-17 19:36:16.715478

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "45a9dba29ff9"
down_revision: str | Sequence[str] | None = "7bc87a340d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notifications_read"))
        batch_op.create_index("ix_notifications_user_id_read", ["user_id", "read"], unique=False)
        batch_op.create_index("ix_notifications_user_id_created_at", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_user_id_created_at")
        batch_op.drop_index("ix_notifications_user_id_read")
        batch_op.create_index(batch_op.f("ix_notifications_read"), ["read"], unique=False)
