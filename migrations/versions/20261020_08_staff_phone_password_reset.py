"""staff phone login and password reset fields

Revision ID: 20261020_08
Revises: 20261020_07
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_08"
down_revision = "20261020_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_users", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("staff_users", sa.Column("password_reset_token_hash", sa.String(64), nullable=True))
    op.add_column("staff_users", sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_staff_users_phone", "staff_users", ["phone"], unique=True)
    op.create_index("ix_staff_users_password_reset_token_hash", "staff_users", ["password_reset_token_hash"])


def downgrade() -> None:
    op.drop_index("ix_staff_users_password_reset_token_hash", table_name="staff_users")
    op.drop_index("ix_staff_users_phone", table_name="staff_users")
    op.drop_column("staff_users", "password_reset_expires_at")
    op.drop_column("staff_users", "password_reset_token_hash")
    op.drop_column("staff_users", "phone")
