"""Durable MCP usage record.

Revision ID: r9a0b1c2d3e4
Revises: q8f9a0b1c2d3
Create Date: 2026-11-19
"""

from alembic import op
import sqlalchemy as sa

revision = "r9a0b1c2d3e4"
down_revision = "q8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("tool", sa.String(80), nullable=True),
        sa.Column("path", sa.String(80), nullable=True),
    )
    op.create_index("ix_mcp_calls_called_at", "mcp_calls", ["called_at"])
    op.create_index("ix_mcp_calls_key_id", "mcp_calls", ["key_id"])
    op.create_index("ix_mcp_calls_tool", "mcp_calls", ["tool"])


def downgrade() -> None:
    op.drop_index("ix_mcp_calls_tool", table_name="mcp_calls")
    op.drop_index("ix_mcp_calls_key_id", table_name="mcp_calls")
    op.drop_index("ix_mcp_calls_called_at", table_name="mcp_calls")
    op.drop_table("mcp_calls")
