"""Evaluation query indexes: fix ORDER BY id DESC LIMIT planner pathology.

Two production query shapes on evaluations (5.4M rows) hit the 30s
statement timeout overnight (Nov 11 2026, postgres log):

  WHERE lab_code = ? AND outcome = 'pass' ORDER BY id DESC LIMIT 1
  WHERE cluster_name = ? ORDER BY id DESC LIMIT 200

With rare/no matching rows the planner prefers a backward primary-key
scan (ORDER BY id DESC LIMIT N) and crawls the whole table filtering as
it goes — 30+ seconds under load. Composite indexes let both shapes be
answered as an index range scan.

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-11-11
"""

from alembic import op

revision = "k1f2a3b4c5d6"
down_revision = "j0e1f2a3b4c5"
branch_labels = None
depends_on = None


def _has_index(bind, table: str, index: str) -> bool:
    from sqlalchemy import inspect
    return any(ix.get("name") == index for ix in inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    # Index builds on 5.4M-row evaluations take 30-40s each — over the
    # server-wide 30s statement_timeout (postgresql.auto.conf), which
    # would cancel the build mid-migration and silently fall back to
    # create_all. Lift it for this transaction only. Measured Nov 11
    # 2026: both indexes build in ~75s total.
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL statement_timeout = 0")
    if not _has_index(bind, "evaluations", "idx_eval_lab_outcome_id"):
        op.create_index("idx_eval_lab_outcome_id", "evaluations", ["lab_code", "outcome", "id"])
    if not _has_index(bind, "evaluations", "idx_eval_cluster_id"):
        op.create_index("idx_eval_cluster_id", "evaluations", ["cluster_name", "id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind, "evaluations", "idx_eval_lab_outcome_id"):
        op.drop_index("idx_eval_lab_outcome_id", table_name="evaluations")
    if _has_index(bind, "evaluations", "idx_eval_cluster_id"):
        op.drop_index("idx_eval_cluster_id", table_name="evaluations")
