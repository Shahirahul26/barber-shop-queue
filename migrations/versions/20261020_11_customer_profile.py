"""customer age and gender profile

Revision ID: 20261020_11
Revises: 20261020_10
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_11"
down_revision = "20261020_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_users", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("customer_users", sa.Column("gender", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_users", "gender")
    op.drop_column("customer_users", "age")
