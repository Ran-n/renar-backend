"""add user background image

Premium profile background banner: users.background_id points at the
content-addressed image store, same pattern as users.avatar_id. The
column is nullable; a missing value means "no background set". Gated
client-side in premium.flair() — the stored image survives a lapse but
is not served to other users while premium is inactive.

Revision ID: f3c1a2b9e045
Revises: e79fbd00fa50
Create Date: 2026-07-12 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c1a2b9e045"
down_revision: str | Sequence[str] | None = "e79fbd00fa50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("background_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_users_background_id_images", "images", ["background_id"], ["id"])
        batch_op.create_index("ix_users_background_id", ["background_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_background_id")
        batch_op.drop_constraint("fk_users_background_id_images", type_="foreignkey")
        batch_op.drop_column("background_id")
