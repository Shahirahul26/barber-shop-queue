"""backfill services and weekly availability for migrated barbers

Revision ID: 20261031_25
Revises: 20261031_24
"""
from alembic import op

revision = "20261031_25"
down_revision = "20261031_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""INSERT INTO barber_service_assignments (membership_id, service_id, is_active)
        SELECT m.id, s.id, true FROM barber_shop_memberships m
        JOIN services s ON s.shop_id=m.shop_id AND s.is_active=true
        WHERE m.is_active=true AND NOT EXISTS (
            SELECT 1 FROM barber_service_assignments a WHERE a.membership_id=m.id AND a.service_id=s.id)""")
    op.execute("""INSERT INTO barber_weekly_availability (membership_id, weekday, starts_at, ends_at, is_active)
        SELECT m.id, day_number, sh.opens_at::time, sh.closes_at::time, true
        FROM barber_shop_memberships m JOIN shops sh ON sh.id=m.shop_id
        CROSS JOIN generate_series(0, 6) AS day_number
        WHERE m.is_active=true AND NOT EXISTS (
            SELECT 1 FROM barber_weekly_availability w WHERE w.membership_id=m.id AND w.weekday=day_number)""")


def downgrade() -> None:
    # These records may have been edited after migration and therefore must not
    # be deleted automatically during a downgrade.
    pass
