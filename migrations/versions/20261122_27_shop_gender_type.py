"""add gender_type to shops

Revision ID: 20261122_27
Revises: 20261110_26
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_27"
down_revision = "20261110_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col["name"] for col in insp.get_columns("shops")]
    if "gender_type" not in columns:
        op.add_column("shops", sa.Column("gender_type", sa.String(length=20), nullable=False, server_default="unisex"))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col["name"] for col in insp.get_columns("shops")]
    if "gender_type" in columns:
        op.drop_column("shops", "gender_type")
