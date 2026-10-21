"""Phase 3 marketplace, appointments, ratings and audit."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_03"
down_revision = "20261019_02"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    op.add_column("shops", sa.Column("slug", sa.String(140), nullable=True))
    op.add_column("shops", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("shops", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("shops", sa.Column("approval_status", sa.String(20), nullable=False, server_default="approved"))
    op.execute("UPDATE shops SET slug = LOWER(REPLACE(name, ' ', '-')) || '-' || id")
    op.alter_column("shops", "slug", nullable=False)
    op.create_index("ix_shops_slug", "shops", ["slug"], unique=True)
    op.create_index("ix_shops_approval_status", "shops", ["approval_status"])
    op.add_column("staff_users", sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "appointments" not in existing_tables:
        op.create_table("appointments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("public_token", sa.String(36), nullable=False), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False), sa.Column("barber_id", sa.Integer(), sa.ForeignKey("barbers.id"), nullable=True), sa.Column("customer_name", sa.String(100), nullable=False), sa.Column("phone", sa.String(20), nullable=False), sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_appointments_public_token", "appointments", ["public_token"], unique=True)
        op.create_index("ix_appointments_shop_id", "appointments", ["shop_id"])
        op.create_index("ix_appointments_scheduled_at", "appointments", ["scheduled_at"])
        op.create_index("ix_appointments_status", "appointments", ["status"])
    if "ratings" not in existing_tables:
        op.create_table("ratings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("queue_entry_id", sa.Integer(), sa.ForeignKey("queue_entries.id"), nullable=True), sa.Column("stars", sa.Integer(), nullable=False), sa.Column("comment", sa.String(500), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_ratings_shop_id", "ratings", ["shop_id"])
        op.create_index("uq_ratings_queue_entry_id", "ratings", ["queue_entry_id"], unique=True)
    if "audit_events" not in existing_tables:
        op.create_table("audit_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=True), sa.Column("actor_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True), sa.Column("action", sa.String(100), nullable=False), sa.Column("details", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_audit_events_shop_id", "audit_events", ["shop_id"])


def downgrade():
    op.drop_table("audit_events")
    op.drop_table("ratings")
    op.drop_table("appointments")
    op.drop_column("staff_users", "is_platform_admin")
    op.drop_index("ix_shops_approval_status", table_name="shops")
    op.drop_index("ix_shops_slug", table_name="shops")
    op.drop_column("shops", "approval_status")
    op.drop_column("shops", "longitude")
    op.drop_column("shops", "latitude")
    op.drop_column("shops", "slug")
