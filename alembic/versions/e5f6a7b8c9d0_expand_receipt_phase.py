"""Expand receipt phase names for functional alignment gates.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "receipts",
        "phase",
        existing_type=sa.String(length=10),
        type_=sa.String(length=100),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "receipts",
        "phase",
        existing_type=sa.String(length=100),
        type_=sa.String(length=10),
        existing_nullable=True,
    )
