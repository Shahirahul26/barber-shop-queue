"""platform banner and shop photo

Revision ID: 20261020_09
Revises: 20261020_08
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_09"
down_revision = "20261020_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("photo_url", sa.String(length=300), nullable=True))
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_column("shops", "photo_url")
