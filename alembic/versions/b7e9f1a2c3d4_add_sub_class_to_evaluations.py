"""Add sub_class column to evaluations.

Revision ID: b7e9f1a2c3d4
Revises: a1b2c3d4e5f6
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "b7e9f1a2c3d4"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("sub_class", sa.String(255), nullable=True))
    op.create_index("ix_evaluations_sub_class", "evaluations", ["sub_class"])


def downgrade() -> None:
    op.drop_index("ix_evaluations_sub_class", "evaluations")
    op.drop_column("evaluations", "sub_class")
