"""Add investigations table for persistent agent investigation storage.

Revision ID: c3d4e5f6g7h8
Revises: b7e9f1a2c3d4
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6g7h8"
down_revision = "b7e9f1a2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(255), unique=True, nullable=False),
        sa.Column("lab_code", sa.String(255), nullable=False),
        sa.Column("cluster", sa.String(100), nullable=True),
        sa.Column("namespace", sa.String(255), nullable=True),
        sa.Column("failure_class", sa.String(255), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("triggering_eval_id", sa.Integer, nullable=True),
        sa.Column("analysis", sa.Text, nullable=True),
        sa.Column("tool_calls", sa.JSON, nullable=True),
        sa.Column("iterations", sa.Integer, nullable=True),
        sa.Column("model_used", sa.String(255), nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("root_cause", sa.String(500), nullable=True),
        sa.Column("remediation_suggestion", sa.Text, nullable=True),
        sa.Column("codebase_link", sa.String(500), nullable=True),
        sa.Column("trust_dimensions", sa.JSON, nullable=True),
        sa.Column("resolved_by_id", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("fallback", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_investigations_job_id", "investigations", ["job_id"], unique=True)
    op.create_index("ix_investigations_lab_code", "investigations", ["lab_code"])
    op.create_index("ix_investigations_cluster", "investigations", ["cluster"])
    op.create_index("ix_investigations_failure_class", "investigations", ["failure_class"])
    op.create_index("idx_inv_lab_fc", "investigations", ["lab_code", "failure_class"])
    op.create_index("idx_inv_status", "investigations", ["status"])


def downgrade() -> None:
    op.drop_index("idx_inv_status", "investigations")
    op.drop_index("idx_inv_lab_fc", "investigations")
    op.drop_index("ix_investigations_failure_class", "investigations")
    op.drop_index("ix_investigations_cluster", "investigations")
    op.drop_index("ix_investigations_lab_code", "investigations")
    op.drop_index("ix_investigations_job_id", "investigations")
    op.drop_table("investigations")
