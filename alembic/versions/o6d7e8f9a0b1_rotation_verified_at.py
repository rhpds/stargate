"""When the audit last verified this snapshot.

Revision ID: o6d7e8f9a0b1
Revises: n5c6d7e8f9a0
Create Date: 2026-11-17
"""

from alembic import op
import sqlalchemy as sa

revision = "o6d7e8f9a0b1"
down_revision = "n5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rotation_snapshots",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rotation_snapshots", "verified_at")
