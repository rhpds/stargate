"""Retention support: created_at indexes on the GeoLux pipeline tables.

The glx_* tables are created out-of-band by the GeoLux pipeline sharing
this database, so they may not exist on fresh environments — every DDL
statement is guarded by an existence check. Indexing created_at lets the
retention job (repository.cleanup_old_glx) delete bounded batches via an
index range scan instead of a seq scan per batch on 7.8M-row tables.

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-11-11
"""

from alembic import op

revision = "j0e1f2a3b4c5"
down_revision = "i9d0e1f2a3b4"
branch_labels = None
depends_on = None

# Mirrors repository.GLX_RETENTION_TABLES — the high-volume event streams.
_GLX_TABLES = (
    "glx_audit_events",
    "glx_routing_decisions",
    "glx_classifications",
    "glx_llm_stability_records",
    "glx_hypotheses",
)


def _has_index(bind, table: str, index: str) -> bool:
    from sqlalchemy import inspect
    if not inspect(bind).has_table(table):
        return True  # nothing to index; treat as satisfied
    return any(ix.get("name") == index for ix in inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    for table in _GLX_TABLES:
        index_name = f"ix_{table}_created_at"
        if not _has_index(bind, table, index_name):
            op.create_index(index_name, table, ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in _GLX_TABLES:
        index_name = f"ix_{table}_created_at"
        if not _has_index(bind, table, index_name):
            op.drop_index(index_name, table_name=table)
