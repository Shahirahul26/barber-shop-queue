"""permanent barber identity memberships availability and scheduling

Revision ID: 20261031_24
Revises: 20261031_23
"""
import sqlalchemy as sa
from alembic import op

revision = "20261031_24"
down_revision = "20261031_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Development startup calls metadata.create_all(). If it ran before
    # Alembic, the new standalone tables exist but legacy tables still lack
    # their new columns. Reconcile that state without dropping any data.
    if "barber_profiles" in inspector.get_table_names():
        profile_columns = {column["name"] for column in inspector.get_columns("barber_profiles")}
        if "legacy_barber_id" not in profile_columns:
            op.add_column("barber_profiles", sa.Column("legacy_barber_id", sa.Integer(), nullable=True))
            op.create_unique_constraint("uq_barber_profiles_legacy_barber_id", "barber_profiles", ["legacy_barber_id"])
        shop_columns = {column["name"] for column in inspector.get_columns("shops")}
        if "appointment_grace_minutes" not in shop_columns:
            op.add_column("shops", sa.Column("appointment_grace_minutes", sa.Integer(), nullable=False, server_default="10"))
        if "cleanup_buffer_minutes" not in shop_columns:
            op.add_column("shops", sa.Column("cleanup_buffer_minutes", sa.Integer(), nullable=False, server_default="0"))
        if "founding_barber_profile_id" not in shop_columns:
            op.add_column("shops", sa.Column("founding_barber_profile_id", sa.Integer(), nullable=True))
            op.create_foreign_key("fk_shops_founding_barber", "shops", "barber_profiles", ["founding_barber_profile_id"], ["id"])
        for table in ("barbers", "staff_users", "appointments", "queue_entries", "ratings"):
            columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
            if "barber_profile_id" not in columns:
                op.add_column(table, sa.Column("barber_profile_id", sa.Integer(), nullable=True))
                op.create_foreign_key(f"fk_{table}_barber_profile", table, "barber_profiles", ["barber_profile_id"], ["id"])
                op.create_index(f"ix_{table}_barber_profile_id", table, ["barber_profile_id"])
        barber_columns = {column["name"] for column in sa.inspect(bind).get_columns("barbers")}
        if "membership_id" not in barber_columns:
            op.add_column("barbers", sa.Column("membership_id", sa.Integer(), nullable=True))
            op.create_foreign_key("fk_barbers_membership", "barbers", "barber_shop_memberships", ["membership_id"], ["id"])
            op.create_index("ix_barbers_membership_id", "barbers", ["membership_id"])
        op.execute("""INSERT INTO barber_profiles (barber_number, legacy_barber_id, full_name, is_active, created_at)
            SELECT 'BRB-' || upper(substr(md5(random()::text || b.id::text), 1, 6)), b.id, b.name, b.is_active, now()
            FROM barbers b WHERE NOT EXISTS (SELECT 1 FROM barber_profiles p WHERE p.legacy_barber_id=b.id)""")
        op.execute("""INSERT INTO barber_shop_memberships (barber_profile_id, shop_id, role, joined_on, status, is_active, display_name, transfer_approval_status)
            SELECT p.id, b.shop_id, 'barber', CURRENT_DATE, CASE WHEN b.is_active THEN 'active' ELSE 'inactive' END, b.is_active, b.name, 'approved'
            FROM barbers b JOIN barber_profiles p ON p.legacy_barber_id=b.id
            WHERE NOT EXISTS (SELECT 1 FROM barber_shop_memberships m WHERE m.barber_profile_id=p.id AND m.shop_id=b.shop_id)""")
        op.execute("""UPDATE barbers b SET barber_profile_id=p.id, membership_id=m.id FROM barber_profiles p, barber_shop_memberships m
            WHERE p.legacy_barber_id=b.id AND m.barber_profile_id=p.id AND m.shop_id=b.shop_id""")
        op.execute("UPDATE staff_users s SET barber_profile_id=b.barber_profile_id FROM barbers b WHERE s.barber_id=b.id")
        for table in ("appointments", "queue_entries", "ratings"):
            op.execute(f"UPDATE {table} x SET barber_profile_id=b.barber_profile_id FROM barbers b WHERE x.barber_id=b.id")
        return
    op.create_table("barber_profiles",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("barber_number", sa.String(20), nullable=False), sa.Column("legacy_barber_id", sa.Integer(), unique=True),
        sa.Column("full_name", sa.String(100), nullable=False), sa.Column("photo_url", sa.String(300)),
        sa.Column("phone", sa.String(20)), sa.Column("email", sa.String(255)), sa.Column("gender", sa.String(30)),
        sa.Column("career_started_on", sa.Date()), sa.Column("biography", sa.Text()), sa.Column("specialities", sa.JSON()),
        sa.Column("certifications", sa.JSON()), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("barber_number"))
    for column in ("barber_number", "phone", "email"):
        op.create_index(f"ix_barber_profiles_{column}", "barber_profiles", [column])
    op.create_table("barber_shop_memberships",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("barber_profile_id", sa.Integer(), sa.ForeignKey("barber_profiles.id"), nullable=False),
        sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("role", sa.String(30), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False), sa.Column("left_on", sa.Date()), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("display_name", sa.String(100)),
        sa.Column("commission_percent", sa.Float()), sa.Column("owner_notes", sa.Text()), sa.Column("transfer_approval_status", sa.String(20), nullable=False))
    op.create_index("ix_barber_shop_memberships_barber_profile_id", "barber_shop_memberships", ["barber_profile_id"])
    op.create_index("ix_barber_shop_memberships_shop_id", "barber_shop_memberships", ["shop_id"])
    op.create_index("ix_barber_shop_memberships_status", "barber_shop_memberships", ["status"])
    op.create_table("barber_service_assignments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("membership_id", sa.Integer(), sa.ForeignKey("barber_shop_memberships.id"), nullable=False), sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.UniqueConstraint("membership_id", "service_id", name="uq_barber_membership_service"))
    op.create_index("ix_barber_service_assignments_membership_id", "barber_service_assignments", ["membership_id"])
    op.create_index("ix_barber_service_assignments_service_id", "barber_service_assignments", ["service_id"])
    op.create_table("barber_weekly_availability", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("membership_id", sa.Integer(), sa.ForeignKey("barber_shop_memberships.id"), nullable=False), sa.Column("weekday", sa.Integer(), nullable=False), sa.Column("starts_at", sa.Time(), nullable=False), sa.Column("ends_at", sa.Time(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False))
    op.create_index("ix_barber_weekly_availability_membership_id", "barber_weekly_availability", ["membership_id"])
    op.create_table("barber_availability_exceptions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("membership_id", sa.Integer(), sa.ForeignKey("barber_shop_memberships.id"), nullable=False), sa.Column("exception_type", sa.String(30), nullable=False), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False), sa.Column("reason", sa.String(300)), sa.Column("approval_status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("membership_id", "starts_at", "ends_at", "approval_status"):
        op.create_index(f"ix_barber_availability_exceptions_{column}", "barber_availability_exceptions", [column])
    op.create_table("barber_membership_requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("barber_profile_id", sa.Integer(), sa.ForeignKey("barber_profiles.id"), nullable=False), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("staff_users.id")), sa.Column("status", sa.String(20), nullable=False), sa.Column("message", sa.String(300)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("responded_at", sa.DateTime(timezone=True)))
    for column in ("barber_profile_id", "shop_id", "status"):
        op.create_index(f"ix_barber_membership_requests_{column}", "barber_membership_requests", [column])
    op.create_table("barber_portfolio_images", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("barber_profile_id", sa.Integer(), sa.ForeignKey("barber_profiles.id"), nullable=False), sa.Column("image_url", sa.String(300), nullable=False), sa.Column("caption", sa.String(160)), sa.Column("sort_order", sa.Integer(), nullable=False))
    op.create_index("ix_barber_portfolio_images_barber_profile_id", "barber_portfolio_images", ["barber_profile_id"])
    op.add_column("shops", sa.Column("appointment_grace_minutes", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("shops", sa.Column("cleanup_buffer_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("shops", sa.Column("founding_barber_profile_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_shops_founding_barber", "shops", "barber_profiles", ["founding_barber_profile_id"], ["id"])
    for table in ("barbers", "staff_users", "appointments", "queue_entries", "ratings"):
        op.add_column(table, sa.Column("barber_profile_id", sa.Integer(), nullable=True))
        op.create_foreign_key(f"fk_{table}_barber_profile", table, "barber_profiles", ["barber_profile_id"], ["id"])
        op.create_index(f"ix_{table}_barber_profile_id", table, ["barber_profile_id"])
    op.add_column("barbers", sa.Column("membership_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_barbers_membership", "barbers", "barber_shop_memberships", ["membership_id"], ["id"])
    op.create_index("ix_barbers_membership_id", "barbers", ["membership_id"])
    # Backfill a permanent identity and active membership for every existing barber.
    op.execute("""INSERT INTO barber_profiles (barber_number, legacy_barber_id, full_name, is_active, created_at)
        SELECT 'BRB-' || upper(substr(md5(random()::text || b.id::text), 1, 6)), b.id, b.name, b.is_active, now() FROM barbers b""")
    op.execute("""INSERT INTO barber_shop_memberships (barber_profile_id, shop_id, role, joined_on, status, is_active, display_name, transfer_approval_status)
        SELECT p.id, b.shop_id, 'barber', CURRENT_DATE, CASE WHEN b.is_active THEN 'active' ELSE 'inactive' END, b.is_active, b.name, 'approved'
        FROM barbers b JOIN barber_profiles p ON p.legacy_barber_id=b.id""")
    op.execute("""UPDATE barbers b SET barber_profile_id=p.id, membership_id=m.id FROM barber_profiles p, barber_shop_memberships m
        WHERE p.legacy_barber_id=b.id AND m.barber_profile_id=p.id AND m.shop_id=b.shop_id""")
    op.execute("UPDATE staff_users s SET barber_profile_id=b.barber_profile_id FROM barbers b WHERE s.barber_id=b.id")
    for table in ("appointments", "queue_entries", "ratings"):
        op.execute(f"UPDATE {table} x SET barber_profile_id=b.barber_profile_id FROM barbers b WHERE x.barber_id=b.id")


def downgrade() -> None:
    for table in ("ratings", "queue_entries", "appointments", "staff_users", "barbers"):
        op.drop_column(table, "barber_profile_id")
    op.drop_column("barbers", "membership_id")
    for column in ("founding_barber_profile_id", "cleanup_buffer_minutes", "appointment_grace_minutes"):
        op.drop_column("shops", column)
    for table in ("barber_portfolio_images", "barber_membership_requests", "barber_availability_exceptions", "barber_weekly_availability", "barber_service_assignments", "barber_shop_memberships", "barber_profiles"):
        op.drop_table(table)
