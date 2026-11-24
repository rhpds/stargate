"""Index the tier-3 freshness probe's (namespace, started_at) filter.

The probe in api/tier3_freshness.py runs every 60 s:

    SELECT namespace, max(started_at) FROM runs
     WHERE namespace IN (<every live namespace>)
     GROUP BY namespace

(No time cutoff: #177 dropped the original 24 h window because it made a
lab starved for more than a day look "never scanned". Retention bounds the
table now — STARGATE_RUN_RETENTION_DAYS, 90 days by default, which is
also the age of the oldest surviving row in production.)

`runs` had indexes on run_id, lab_code and cluster_name — nothing that
helps this. Measured on production 2026-11-23 at 608k rows / 323 MB:
1,501 ms per call, two parallel seq scans over the whole table, 54.5k
buffer reads. It is a fixed 60 s cost that grows with the table, not with
the work. With the composite index the same query, same data, same
production connection measured 64.0 ms — one index-only scan, 10.9k
buffers (20.6 ms if the 24 h window is kept, for comparison).

Column order is (namespace, started_at), matching the filter: the query
visits ~923 namespaces and wants the newest started_at within each.

Built without CONCURRENTLY, deliberately, unlike the evaluations index
migrations. Two reasons, both measured:

- The build is short. `CREATE INDEX` on the live table in a rolled-back
  transaction took 2.95 s. It holds a SHARE lock for that long, which
  blocks writes but not reads; `runs` gains ~14 rows/min, so that is a
  couple of inserts queued for 3 s, well inside the scanner's 10 s client
  timeout.
- A failed CONCURRENTLY build leaves an INVALID index behind. init_db()
  swallows migration errors and falls back to create_all(), so that index
  would then be hidden rather than repaired, and every subsequent startup
  would hit the same invalid-index check. A plain build is transactional:
  if it fails it rolls back to nothing.

If `runs` is ever re-indexed at a much larger size, use CONCURRENTLY in an
autocommit block — see g7b8c9d0e1f2 for the pattern and the validity check
that pattern needs.

init_db() runs `alembic upgrade head` on API startup (db/database.py), so
this lands with the next API deploy rather than needing a manual step.

Revision ID: s0b1c2d3e4f5
Revises: r9a0b1c2d3e4
Create Date: 2026-11-23
"""

from alembic import op

revision = "s0b1c2d3e4f5"
down_revision = "r9a0b1c2d3e4"
branch_labels = None
depends_on = None

_INDEX = "idx_runs_namespace_started_at"
_COLUMNS = ["namespace", "started_at"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The server-wide statement_timeout (postgresql.auto.conf, 30 s) is
        # below what a future build of this table could take. Scoped to this
        # migration's transaction; alembic env.py disposes its engine after.
        op.execute("SET LOCAL statement_timeout = 0")
    op.create_index(_INDEX, "runs", _COLUMNS, if_not_exists=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL statement_timeout = 0")
    op.drop_index(_INDEX, table_name="runs", if_exists=True)
