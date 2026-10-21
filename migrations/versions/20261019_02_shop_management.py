"""Add shop profile, staff names, and service activation."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_02"
down_revision = "20261018_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("shops", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("shops", sa.Column("gst_number", sa.String(15), nullable=True))
    op.add_column("staff_users", sa.Column("name", sa.String(100), nullable=False, server_default="Shop Owner"))
    op.add_column("services", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("services", "is_active")
    op.drop_column("staff_users", "name")
    op.drop_column("shops", "gst_number")
    op.drop_column("shops", "phone")
