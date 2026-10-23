"""support multiple services and unassigned online queue entries

Revision ID: 20261022_19
Revises: 20261022_18
"""
import sqlalchemy as sa
from alembic import op

revision = "20261022_19"
down_revision = "20261022_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queue_entries", sa.Column("service_ids", sa.JSON(), nullable=True))
    op.add_column("queue_entries", sa.Column("service_names", sa.String(500), nullable=True))
    op.add_column("queue_entries", sa.Column("total_duration_minutes", sa.Integer(), nullable=True))
    op.add_column("queue_entries", sa.Column("total_price_rupees", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE queue_entries AS q
        SET service_ids = json_build_array(q.service_id),
            service_names = s.name,
            total_duration_minutes = s.duration_minutes,
            total_price_rupees = s.price_rupees
        FROM services AS s
        WHERE s.id = q.service_id
    """)
    op.alter_column("queue_entries", "service_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM queue_entries WHERE service_id IS NULL")
    op.alter_column("queue_entries", "service_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("queue_entries", "total_price_rupees")
    op.drop_column("queue_entries", "total_duration_minutes")
    op.drop_column("queue_entries", "service_names")
    op.drop_column("queue_entries", "service_ids")
