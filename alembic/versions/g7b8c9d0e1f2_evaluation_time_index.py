"""Index evaluation time filters without blocking ordinary PostgreSQL writes."""
from alembic import op
import sqlalchemy as sa

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        # IF NOT EXISTS alone does not establish that a prior build is valid.
        existing = op.get_bind().execute(sa.text("""
            SELECT i.indisvalid, i.indisready, pg_get_indexdef(i.indexrelid) AS definition
            FROM pg_index i WHERE i.indexrelid=to_regclass('public.idx_eval_evaluated_at')
        """)).mappings().first()
        if existing:
            if (not existing["indisvalid"] or not existing["indisready"] or
                    not existing["definition"].startswith("CREATE INDEX ") or
                    not existing["definition"].endswith("USING btree (evaluated_at)") or
                    "public.evaluations " not in existing["definition"]):
                raise RuntimeError("Existing evaluation time index is invalid or mismatched; inspect before retrying")
            return
        with op.get_context().autocommit_block():
            op.create_index("idx_eval_evaluated_at", "evaluations", ["evaluated_at"],
                            schema="public", postgresql_concurrently=True, if_not_exists=True)
    else:
        op.create_index("idx_eval_evaluated_at", "evaluations", ["evaluated_at"], if_not_exists=True)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index("idx_eval_evaluated_at", table_name="evaluations", schema="public",
                          postgresql_concurrently=True, if_exists=True)
    else:
        op.drop_index("idx_eval_evaluated_at", table_name="evaluations", if_exists=True)
