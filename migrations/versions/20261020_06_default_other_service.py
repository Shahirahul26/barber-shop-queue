"""add fallback Other service for shops without services

Revision ID: 20261020_06
Revises: 20261019_05
"""
from alembic import op

revision = "20261020_06"
down_revision = "20261019_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO services (shop_id, name, duration_minutes, price_rupees, is_active)
        SELECT shops.id, 'Other', 20, 0, true
        FROM shops
        WHERE NOT EXISTS (
            SELECT 1 FROM services
            WHERE services.shop_id = shops.id AND services.is_active = true
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM services WHERE name = 'Other' AND duration_minutes = 20 AND price_rupees = 0")
