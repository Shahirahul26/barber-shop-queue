"""staff password management

Revision ID: 20261019_04
Revises: 20261019_03
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20261019_04"
down_revision = "20261019_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("staff_users", "must_change_password", server_default=None)


def downgrade() -> None:
    op.drop_column("staff_users", "must_change_password")
