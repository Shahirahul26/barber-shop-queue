"""customer otp authentication

Revision ID: 20261020_10
Revises: 20261020_09
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_10"
down_revision = "20261020_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("customer_users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(100), nullable=True), sa.Column("email", sa.String(255), nullable=True), sa.Column("phone", sa.String(20), nullable=True), sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True), sa.Column("otp_hash", sa.String(64), nullable=True), sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True), sa.Column("otp_sent_at", sa.DateTime(timezone=True), nullable=True), sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_customer_users_email", "customer_users", ["email"], unique=True)
    op.create_index("ix_customer_users_phone", "customer_users", ["phone"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_customer_users_phone", table_name="customer_users")
    op.drop_index("ix_customer_users_email", table_name="customer_users")
    op.drop_table("customer_users")
