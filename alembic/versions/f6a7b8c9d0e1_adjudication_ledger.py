"""Add the bounded, review-only adjudication ledger."""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "adjudications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("diagnosis_version", sa.Integer(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("reviews", sa.JSON()), sa.Column("judge", sa.JSON()),
        sa.Column("reason", sa.String(255)), sa.Column("total_tokens", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("investigation_id", "diagnosis_version", "evidence_hash", name="uq_adjudication_evidence"),
    )
    op.create_index("idx_adjudication_created", "adjudications", ["created_at"])


def downgrade():
    op.drop_table("adjudications")
