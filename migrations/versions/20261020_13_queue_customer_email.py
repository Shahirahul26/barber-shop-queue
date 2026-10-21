"""add optional customer email to queue entries

Revision ID: 20261020_13
Revises: 20261020_12
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_13"
down_revision = "20261020_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queue_entries", sa.Column("email", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("queue_entries", "email")
