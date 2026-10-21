"""link due appointments to priority queue entries

Revision ID: 20261020_07
Revises: 20261020_06
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_07"
down_revision = "20261020_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queue_entries", sa.Column("appointment_id", sa.Integer(), nullable=True))
    op.create_index("ix_queue_entries_appointment_id", "queue_entries", ["appointment_id"], unique=True)
    op.create_foreign_key("fk_queue_entries_appointment_id", "queue_entries", "appointments", ["appointment_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_queue_entries_appointment_id", "queue_entries", type_="foreignkey")
    op.drop_index("ix_queue_entries_appointment_id", table_name="queue_entries")
    op.drop_column("queue_entries", "appointment_id")
