"""add barber ratings and reviews

Revision ID: 20261021_14
Revises: 20261020_13
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_14"
down_revision = "20261020_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ratings", sa.Column("barber_id", sa.Integer(), nullable=True))
    op.add_column("ratings", sa.Column("barber_stars", sa.Integer(), nullable=True))
    op.add_column("ratings", sa.Column("barber_comment", sa.String(length=500), nullable=True))
    op.create_index("ix_ratings_barber_id", "ratings", ["barber_id"], unique=False)
    op.create_foreign_key("fk_ratings_barber_id", "ratings", "barbers", ["barber_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_ratings_barber_id", "ratings", type_="foreignkey")
    op.drop_index("ix_ratings_barber_id", table_name="ratings")
    op.drop_column("ratings", "barber_comment")
    op.drop_column("ratings", "barber_stars")
    op.drop_column("ratings", "barber_id")
