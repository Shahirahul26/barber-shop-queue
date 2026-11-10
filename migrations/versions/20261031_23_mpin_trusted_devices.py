"""add customer and staff mpin trusted-device authentication

Revision ID: 20261031_23
Revises: 20261023_22
"""
import sqlalchemy as sa
from alembic import op

revision = "20261031_23"
down_revision = "20261023_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("customer_users", "staff_users"):
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "mpin_hash" not in existing:
            op.add_column(table, sa.Column("mpin_hash", sa.String(255), nullable=True))
        if "mpin_set_at" not in existing:
            op.add_column(table, sa.Column("mpin_set_at", sa.DateTime(timezone=True), nullable=True))
        if "mpin_failed_attempts" not in existing:
            op.add_column(table, sa.Column("mpin_failed_attempts", sa.Integer(), nullable=False, server_default="0"))
        if "mpin_locked_until" not in existing:
            op.add_column(table, sa.Column("mpin_locked_until", sa.DateTime(timezone=True), nullable=True))
    if "trusted_device_sessions" not in inspector.get_table_names():
        op.create_table(
            "trusted_device_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer_users.id"), nullable=True),
            sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
            sa.Column("device_id", sa.String(64), nullable=False),
            sa.Column("device_name", sa.String(160), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("customer_id", "device_id", name="uq_customer_trusted_device"),
            sa.UniqueConstraint("staff_user_id", "device_id", name="uq_staff_trusted_device"),
            sa.CheckConstraint("(customer_id IS NOT NULL) <> (staff_user_id IS NOT NULL)", name="ck_trusted_device_one_account"),
        )
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("trusted_device_sessions")}
    for name, column in (("ix_trusted_device_sessions_customer_id", "customer_id"), ("ix_trusted_device_sessions_staff_user_id", "staff_user_id"), ("ix_trusted_device_sessions_device_id", "device_id")):
        if name not in existing_indexes:
            op.create_index(name, "trusted_device_sessions", [column])
    existing_checks = {constraint["name"] for constraint in sa.inspect(bind).get_check_constraints("trusted_device_sessions")}
    if "ck_trusted_device_one_account" not in existing_checks:
        op.create_check_constraint("ck_trusted_device_one_account", "trusted_device_sessions", "(customer_id IS NOT NULL) <> (staff_user_id IS NOT NULL)")


def downgrade() -> None:
    op.drop_table("trusted_device_sessions")
    for table in ("staff_users", "customer_users"):
        op.drop_column(table, "mpin_locked_until")
        op.drop_column(table, "mpin_failed_attempts")
        op.drop_column(table, "mpin_set_at")
        op.drop_column(table, "mpin_hash")
