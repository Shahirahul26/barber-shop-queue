"""link queue entries and appointments to customer accounts

Revision ID: 20261021_15
Revises: 20261021_14
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_15"
down_revision = "20261021_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queue_entries", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("appointments", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_index("ix_queue_entries_customer_id", "queue_entries", ["customer_id"], unique=False)
    op.create_index("ix_appointments_customer_id", "appointments", ["customer_id"], unique=False)
    op.create_foreign_key("fk_queue_entries_customer_id", "queue_entries", "customer_users", ["customer_id"], ["id"])
    op.create_foreign_key("fk_appointments_customer_id", "appointments", "customer_users", ["customer_id"], ["id"])
    op.execute("UPDATE queue_entries q SET customer_id = c.id FROM customer_users c WHERE q.customer_id IS NULL AND ((q.phone IS NOT NULL AND q.phone = c.phone) OR (q.email IS NOT NULL AND lower(q.email) = lower(c.email)))")
    op.execute("UPDATE appointments a SET customer_id = c.id FROM customer_users c WHERE a.customer_id IS NULL AND a.phone IS NOT NULL AND a.phone = c.phone")


def downgrade() -> None:
    op.drop_constraint("fk_appointments_customer_id", "appointments", type_="foreignkey")
    op.drop_constraint("fk_queue_entries_customer_id", "queue_entries", type_="foreignkey")
    op.drop_index("ix_appointments_customer_id", table_name="appointments")
    op.drop_index("ix_queue_entries_customer_id", table_name="queue_entries")
    op.drop_column("appointments", "customer_id")
    op.drop_column("queue_entries", "customer_id")
