"""add appointments_enabled to shops

Revision ID: 20261110_26
Revises: 20261031_25
"""
from alembic import op
import sqlalchemy as sa

revision = "20261110_26"
down_revision = "20261031_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col["name"] for col in insp.get_columns("shops")]
    if "appointments_enabled" not in columns:
        op.add_column("shops", sa.Column("appointments_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col["name"] for col in insp.get_columns("shops")]
    if "appointments_enabled" in columns:
        op.drop_column("shops", "appointments_enabled")
