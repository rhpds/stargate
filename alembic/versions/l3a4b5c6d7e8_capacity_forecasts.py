"""Capacity forecast persistence — the authority gate's evidence base.

Revision ID: l3a4b5c6d7e8
Revises: k1f2a3b4c5d6
Create Date: 2026-11-13
"""

from alembic import op
import sqlalchemy as sa

revision = "l3a4b5c6d7e8"
down_revision = "k1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("authority", sa.String(20), nullable=False, server_default="advisory"),
        sa.Column("supply_vm_slots", sa.Float(), nullable=True),
        sa.Column("supply_basis", sa.String(50), nullable=True),
        sa.Column("sessions_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sessions_with_profiles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sessions_fallback", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("peak_hour", sa.JSON(), nullable=True),
        sa.Column("hourly", sa.JSON(), nullable=True),
    )
    op.create_index("ix_capacity_forecasts_generated_at", "capacity_forecasts", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_capacity_forecasts_generated_at", table_name="capacity_forecasts")
    op.drop_table("capacity_forecasts")
