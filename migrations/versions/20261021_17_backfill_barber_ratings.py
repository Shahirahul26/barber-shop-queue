"""backfill assigned barber ratings from shop score

Revision ID: 20261021_17
Revises: 20261021_16
"""
from alembic import op

revision = "20261021_17"
down_revision = "20261021_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE ratings SET barber_stars = stars WHERE barber_id IS NOT NULL AND barber_stars IS NULL")


def downgrade() -> None:
    pass
