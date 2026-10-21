"""Phase 2 PostgreSQL-ready schema."""
from alembic import op
import sqlalchemy as sa

revision = "20261018_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("shops", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("address", sa.String(240), nullable=False), sa.Column("timezone", sa.String(64), nullable=False), sa.Column("opens_at", sa.String(5), nullable=False), sa.Column("closes_at", sa.String(5), nullable=False), sa.Column("queue_paused", sa.Boolean(), nullable=False))
    op.create_table("barbers", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False))
    op.create_index("ix_barbers_shop_id", "barbers", ["shop_id"])
    op.create_table("services", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False), sa.Column("price_rupees", sa.Integer(), nullable=False))
    op.create_index("ix_services_shop_id", "services", ["shop_id"])
    op.create_table("staff_users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("email", sa.String(255), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_staff_users_shop_id", "staff_users", ["shop_id"])
    op.create_index("ix_staff_users_email", "staff_users", ["email"], unique=True)
    op.create_table("queue_entries", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("public_token", sa.String(36), nullable=False), sa.Column("shop_id", sa.Integer(), sa.ForeignKey("shops.id"), nullable=False), sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False), sa.Column("barber_id", sa.Integer(), sa.ForeignKey("barbers.id"), nullable=True), sa.Column("customer_name", sa.String(100), nullable=False), sa.Column("phone", sa.String(20), nullable=True), sa.Column("status", sa.String(9), nullable=False), sa.Column("source", sa.String(20), nullable=False), sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("two_ahead_notified_at", sa.DateTime(timezone=True), nullable=True), sa.Column("next_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_queue_entries_public_token", "queue_entries", ["public_token"], unique=True)
    op.create_index("ix_queue_entries_shop_id", "queue_entries", ["shop_id"])
    op.create_index("ix_queue_entries_status", "queue_entries", ["status"])
    op.create_table("push_subscriptions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("queue_entry_id", sa.Integer(), sa.ForeignKey("queue_entries.id"), nullable=False), sa.Column("endpoint", sa.String(1000), nullable=False), sa.Column("p256dh", sa.String(255), nullable=False), sa.Column("auth", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_push_subscriptions_queue_entry_id", "push_subscriptions", ["queue_entry_id"])
    op.create_index("ix_push_subscriptions_endpoint", "push_subscriptions", ["endpoint"], unique=True)


def downgrade():
    op.drop_table("push_subscriptions")
    op.drop_table("queue_entries")
    op.drop_table("staff_users")
    op.drop_table("services")
    op.drop_table("barbers")
    op.drop_table("shops")
