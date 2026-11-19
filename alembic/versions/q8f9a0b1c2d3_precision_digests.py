"""Stored precision digests for the RAG corpus.

Revision ID: q8f9a0b1c2d3
Revises: p7e8f9a0b1c2
Create Date: 2026-11-19
"""

from alembic import op
import sqlalchemy as sa

revision = "q8f9a0b1c2d3"
down_revision = "p7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "precision_digests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period", sa.String(20), nullable=False, unique=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_precision_digests_generated_at", "precision_digests", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_precision_digests_generated_at", table_name="precision_digests")
    op.drop_table("precision_digests")
