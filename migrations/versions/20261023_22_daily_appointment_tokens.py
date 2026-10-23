"""add shop-and-service-date appointment token numbers

Revision ID: 20261023_22
Revises: 20261023_21
"""
import sqlalchemy as sa
from alembic import op

revision = "20261023_22"
down_revision = "20261023_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("booking_day", sa.Date(), nullable=True))
    op.add_column("appointments", sa.Column("daily_booking_number", sa.Integer(), nullable=True))
    op.execute("""
        WITH ranked AS (
            SELECT a.id,
                   (a.scheduled_at AT TIME ZONE COALESCE(s.timezone, 'Asia/Kolkata'))::date AS local_day,
                   row_number() OVER (
                       PARTITION BY a.shop_id, (a.scheduled_at AT TIME ZONE COALESCE(s.timezone, 'Asia/Kolkata'))::date
                       ORDER BY a.scheduled_at, a.id
                   ) AS daily_number
            FROM appointments a
            JOIN shops s ON s.id = a.shop_id
        )
        UPDATE appointments a
        SET booking_day = ranked.local_day,
            daily_booking_number = ranked.daily_number
        FROM ranked
        WHERE a.id = ranked.id
    """)
    op.create_index("ix_appointments_booking_day", "appointments", ["booking_day"])
    op.create_unique_constraint("uq_appointment_daily_token", "appointments", ["shop_id", "booking_day", "daily_booking_number"])


def downgrade() -> None:
    op.drop_constraint("uq_appointment_daily_token", "appointments", type_="unique")
    op.drop_index("ix_appointments_booking_day", table_name="appointments")
    op.drop_column("appointments", "daily_booking_number")
    op.drop_column("appointments", "booking_day")
