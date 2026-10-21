"""allow email-only customers to book appointments

Revision ID: 20261020_12
Revises: 20261020_11
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_12"
down_revision = "20261020_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("appointments", "phone", existing_type=sa.String(length=20), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE appointments SET phone = '' WHERE phone IS NULL")
    op.alter_column("appointments", "phone", existing_type=sa.String(length=20), nullable=False)
