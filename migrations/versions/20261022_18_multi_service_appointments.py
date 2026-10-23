"""support multiple services in one appointment

Revision ID: 20261022_18
Revises: 20261021_17
"""
import sqlalchemy as sa
from alembic import op

revision = "20261022_18"
down_revision = "20261021_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("service_ids", sa.JSON(), nullable=True))
    op.add_column("appointments", sa.Column("service_names", sa.String(500), nullable=True))
    op.add_column("appointments", sa.Column("total_duration_minutes", sa.Integer(), nullable=True))
    op.add_column("appointments", sa.Column("total_price_rupees", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE appointments AS a
        SET service_ids = json_build_array(a.service_id),
            service_names = s.name,
            total_duration_minutes = s.duration_minutes,
            total_price_rupees = s.price_rupees
        FROM services AS s
        WHERE s.id = a.service_id
    """)
    op.alter_column("appointments", "service_ids", nullable=False)
    op.alter_column("appointments", "service_names", nullable=False)
    op.alter_column("appointments", "total_duration_minutes", nullable=False)
    op.alter_column("appointments", "total_price_rupees", nullable=False)


def downgrade() -> None:
    op.drop_column("appointments", "total_price_rupees")
    op.drop_column("appointments", "total_duration_minutes")
    op.drop_column("appointments", "service_names")
    op.drop_column("appointments", "service_ids")
