"""Recurrence tracking on investigations + known_issues fleet rollup table.

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa

revision = "i9d0e1f2a3b4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- investigations: recurrence tracking (dedup attaches here) ---
    op.add_column("investigations", sa.Column("recurrence_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("investigations", sa.Column("last_recurrence_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("investigations", sa.Column("recurrence_log", sa.JSON(), nullable=True))

    # --- known_issues: fleet-level rollup ---
    op.create_table(
        "known_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signature", sa.String(255), nullable=False),
        sa.Column("bucket", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("failure_class", sa.String(255), nullable=True),
        sa.Column("cluster", sa.String(100), nullable=True),
        sa.Column("artifact_refs", sa.JSON(), nullable=True),
        sa.Column("namespace_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("investigation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("investigation_ids", sa.JSON(), nullable=True),
        sa.Column("representative_investigation_id", sa.Integer(), nullable=True),
        sa.Column("top_root_cause_excerpt", sa.Text(), nullable=True),
        sa.Column("remediation_excerpt", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_known_issues_signature", "known_issues", ["signature"], unique=True)
    op.create_index("idx_known_issue_status", "known_issues", ["status"])
    op.create_index("idx_known_issue_bucket", "known_issues", ["bucket"])


def downgrade() -> None:
    op.drop_index("idx_known_issue_bucket", "known_issues")
    op.drop_index("idx_known_issue_status", "known_issues")
    op.drop_index("ix_known_issues_signature", "known_issues")
    op.drop_table("known_issues")
    op.drop_column("investigations", "recurrence_log")
    op.drop_column("investigations", "last_recurrence_at")
    op.drop_column("investigations", "recurrence_count")
