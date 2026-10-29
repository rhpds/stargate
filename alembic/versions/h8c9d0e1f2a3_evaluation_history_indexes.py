"""Indexes for exact per-namespace history probes; no retention/window change."""
from alembic import op
import sqlalchemy as sa

revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None

INDEXES = {
    "idx_eval_lab_first_seen": ["lab_code", "evaluated_at"],
    "idx_eval_lab_failure_latest": ["lab_code", "failure_class", "id"],
}


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    for name, columns in INDEXES.items():
        if postgres:
            existing = op.get_bind().execute(sa.text("""
                SELECT i.indisvalid, i.indisready, pg_get_indexdef(i.indexrelid) AS definition
                FROM pg_index i WHERE i.indexrelid=to_regclass(:index_name)
            """), {"index_name": "public." + name}).mappings().first()
            if existing:
                if (not existing["indisvalid"] or not existing["indisready"] or
                        not existing["definition"].startswith("CREATE INDEX ") or
                        "public.evaluations " not in existing["definition"] or
                        not existing["definition"].endswith("USING btree (" + ", ".join(columns) + ")")):
                    raise RuntimeError("Existing history index is invalid or mismatched: " + name)
                continue
            with op.get_context().autocommit_block():
                op.create_index(name, "evaluations", columns, schema="public",
                                postgresql_concurrently=True, if_not_exists=True)
        else:
            op.create_index(name, "evaluations", columns, if_not_exists=True)


def downgrade():
    for name in reversed(INDEXES):
        if op.get_bind().dialect.name == "postgresql":
            with op.get_context().autocommit_block():
                op.drop_index(name, table_name="evaluations", schema="public",
                              postgresql_concurrently=True, if_exists=True)
        else:
            op.drop_index(name, table_name="evaluations", if_exists=True)
