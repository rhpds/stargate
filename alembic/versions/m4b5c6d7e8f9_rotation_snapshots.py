"""Rotation snapshots — one row per provider per day.

Backs the rotation page: ticket counters from the Jira sync and verified-live
counters from the audit ingest. Unique on (snapshot_date, provider) so both
writers are idempotent and the trend stays one point per day.

Revision ID: m4b5c6d7e8f9
Revises: l3a4b5c6d7e8
Create Date: 2026-11-17
"""

from alembic import op
import sqlalchemy as sa

revision = "m4b5c6d7e8f9"
down_revision = "l3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rotation_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unassigned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_live", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("live_locations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("untracked_live", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "snapshot_date", "provider", name="uq_rotation_snapshot_day_provider"
        ),
    )
    op.create_index(
        "ix_rotation_snapshots_snapshot_date", "rotation_snapshots", ["snapshot_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_rotation_snapshots_snapshot_date", table_name="rotation_snapshots")
    op.drop_table("rotation_snapshots")
