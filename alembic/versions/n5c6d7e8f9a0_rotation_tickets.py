"""Rotation tickets — the provider drill-down.

Revision ID: n5c6d7e8f9a0
Revises: m4b5c6d7e8f9
Create Date: 2026-11-17
"""

from alembic import op
import sqlalchemy as sa

revision = "n5c6d7e8f9a0"
down_revision = "m4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rotation_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("issue_key", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("assignee", sa.String(120), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rotation_tickets_issue_key", "rotation_tickets", ["issue_key"], unique=True)
    op.create_index("ix_rotation_tickets_provider", "rotation_tickets", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_rotation_tickets_provider", table_name="rotation_tickets")
    op.drop_index("ix_rotation_tickets_issue_key", table_name="rotation_tickets")
    op.drop_table("rotation_tickets")
