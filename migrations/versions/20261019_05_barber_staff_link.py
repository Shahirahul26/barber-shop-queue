"""link staff logins to barber profiles

Revision ID: 20261019_05
Revises: 20261019_04
"""
from alembic import op
import sqlalchemy as sa

revision = "20261019_05"
down_revision = "20261019_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_users", sa.Column("barber_id", sa.Integer(), nullable=True))
    op.create_index("ix_staff_users_barber_id", "staff_users", ["barber_id"])
    op.create_foreign_key("fk_staff_users_barber_id", "staff_users", "barbers", ["barber_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_staff_users_barber_id", "staff_users", type_="foreignkey")
    op.drop_index("ix_staff_users_barber_id", table_name="staff_users")
    op.drop_column("staff_users", "barber_id")
