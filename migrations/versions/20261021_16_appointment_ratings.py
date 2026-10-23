"""allow ratings for completed appointments

Revision ID: 20261021_16
Revises: 20261021_15
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_16"
down_revision = "20261021_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ratings", sa.Column("appointment_id", sa.Integer(), nullable=True))
    op.create_index("uq_ratings_appointment_id", "ratings", ["appointment_id"], unique=True)
    op.create_foreign_key("fk_ratings_appointment_id", "ratings", "appointments", ["appointment_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_ratings_appointment_id", "ratings", type_="foreignkey")
    op.drop_index("uq_ratings_appointment_id", table_name="ratings")
    op.drop_column("ratings", "appointment_id")
