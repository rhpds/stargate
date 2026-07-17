"""Add quality columns to proposed_classifications.

Revision ID: a1b2c3d4e5f6
Revises: 87394f2021f5
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "87394f2021f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("proposed_classifications", sa.Column("quality_outcome", sa.String(10), nullable=True))
    op.add_column("proposed_classifications", sa.Column("quality_passed", sa.Boolean(), nullable=True))
    op.add_column("proposed_classifications", sa.Column("quality_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("proposed_classifications", "quality_details")
    op.drop_column("proposed_classifications", "quality_passed")
    op.drop_column("proposed_classifications", "quality_outcome")
