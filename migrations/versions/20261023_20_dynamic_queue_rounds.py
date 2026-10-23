"""support end-of-queue skipping and appointment priority release

Revision ID: 20261023_20
Revises: 20261022_19
"""
import sqlalchemy as sa
from alembic import op

revision = "20261023_20"
down_revision = "20261022_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queue_entries", sa.Column("priority_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE queue_entries SET status = 'WAITING', joined_at = CURRENT_TIMESTAMP, priority_active = false WHERE status = 'SKIPPED'")


def downgrade() -> None:
    op.drop_column("queue_entries", "priority_active")
