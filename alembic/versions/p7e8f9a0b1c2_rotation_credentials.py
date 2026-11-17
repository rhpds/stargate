"""Per-credential coverage for the rotation page.

Revision ID: p7e8f9a0b1c2
Revises: o6d7e8f9a0b1
Create Date: 2026-11-17
"""

from alembic import op
import sqlalchemy as sa

revision = "p7e8f9a0b1c2"
down_revision = "o6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rotation_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("credential_id", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("credential", sa.String(200), nullable=False),
        sa.Column("live_copies", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clusters", sa.String(500), nullable=True),
        sa.Column("example_location", sa.String(300), nullable=True),
        sa.Column("coverage", sa.String(30), nullable=True),
        sa.Column("jira_keys", sa.String(200), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("snapshot_date", "credential_id", name="uq_rotation_credential_day_id"),
    )
    op.create_index("ix_rotation_credentials_snapshot_date", "rotation_credentials", ["snapshot_date"])
    op.create_index("ix_rotation_credentials_credential_id", "rotation_credentials", ["credential_id"])
    op.create_index("ix_rotation_credentials_provider", "rotation_credentials", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_rotation_credentials_provider", table_name="rotation_credentials")
    op.drop_index("ix_rotation_credentials_credential_id", table_name="rotation_credentials")
    op.drop_index("ix_rotation_credentials_snapshot_date", table_name="rotation_credentials")
    op.drop_table("rotation_credentials")
