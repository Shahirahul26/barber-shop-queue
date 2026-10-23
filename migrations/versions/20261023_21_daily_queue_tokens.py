"""add shop-local daily live queue token numbers

Revision ID: 20261023_21
Revises: 20261023_20
"""
import sqlalchemy as sa
from alembic import op

revision = "20261023_21"
down_revision = "20261023_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queue_entries", sa.Column("queue_day", sa.Date(), nullable=True))
    op.add_column("queue_entries", sa.Column("daily_token_number", sa.Integer(), nullable=True))
    op.execute("""
        WITH ranked AS (
            SELECT q.id,
                   (q.joined_at AT TIME ZONE COALESCE(s.timezone, 'Asia/Kolkata'))::date AS local_day,
                   row_number() OVER (
                       PARTITION BY q.shop_id, (q.joined_at AT TIME ZONE COALESCE(s.timezone, 'Asia/Kolkata'))::date
                       ORDER BY q.joined_at, q.id
                   ) AS daily_number
            FROM queue_entries q
            JOIN shops s ON s.id = q.shop_id
            WHERE q.appointment_id IS NULL
        )
        UPDATE queue_entries q
        SET queue_day = ranked.local_day,
            daily_token_number = ranked.daily_number
        FROM ranked
        WHERE q.id = ranked.id
    """)
    op.create_index("ix_queue_entries_queue_day", "queue_entries", ["queue_day"])
    op.create_unique_constraint("uq_queue_daily_token", "queue_entries", ["shop_id", "queue_day", "daily_token_number"])


def downgrade() -> None:
    op.drop_constraint("uq_queue_daily_token", "queue_entries", type_="unique")
    op.drop_index("ix_queue_entries_queue_day", table_name="queue_entries")
    op.drop_column("queue_entries", "daily_token_number")
    op.drop_column("queue_entries", "queue_day")
