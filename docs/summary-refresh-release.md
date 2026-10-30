# Summary-refresh release and writer handoff

Status: locally validated; not deployed. This procedure is a proposal, not
authorization to stop services or change production configuration.

The release aggregates the full 24-hour evaluation window in SQL and uses a
nonblocking, transaction-owned PostgreSQL advisory lock per summary type. A busy
worker skips before reading history. Failed refreshes roll back; readers retain
the previous committed summary until the replacement commits.

## Preconditions

- Obtain explicit approval for the rollout and a brief API interruption. Do not
  use a normal overlapping rolling update: old workers do not take these locks.
- Pin every OpenShift command to the verified infra01 context and application
  namespace. Do not change the active context or access workload clusters.
- Recheck the live immutable image, Deployment UID/spec fingerprint, replica
  count, resource settings, database head, and dry-run/execution-target flags.
  Previous receipts are comparison evidence, not fresh authorization.
- Verify the new registry digest against the tested local image and source
  manifest. A mutable tag or inherited base revision label is insufficient.
- Verify no new migrations, provider credentials, model/adjudication changes,
  historical receipts, or unrelated working-checkout changes enter the release.
- Inventory **all** summary writers. Source entry points include the API's
  background refresh loop and `tasks.maintenance.mv_refresh` scheduled by Celery
  beat. API replica replacement alone is not proof that every old writer stopped.
- Resolve any active external maintenance writer, queued/retrying refresh task,
  scheduler, scaling controller, or GitOps reconciliation before proceeding.
  If additional worker/scheduler changes would be needed, obtain approval for
  those exact targets. Do not stop unrelated collectors or investigations.
- Record the rollback digest and a protected configuration snapshot outside
  source control. Do not print secrets or dump environment values into receipts.

## Controlled handoff

1. Recheck the preconditions immediately before each mutation. Stop if identity,
   replica count, configuration, scope, or the approved window changed.
2. Prevent approved legacy maintenance writers from starting or retrying refresh
   work. Drain in-flight work and verify the absence of old writers against the
   database. Do not purge queues or terminate arbitrary database sessions.
3. Stop the old API replicas using the approved zero-overlap procedure. Wait for
   their pods to be fully terminated, not merely unready. The API is unavailable
   during this interval; ingestion continuity must be checked independently.
4. Only after all old writers are absent, select the verified new immutable
   image and start one API replica. Do not change credentials, models, diagnosis
   promotion flags, remediation controls, or database schema.
5. Observe startup and repeated summary refreshes. Verify complete logical keys,
   no duplicates, expected nonzero/zero counts, summary freshness, query latency,
   HTTP responsiveness, ingestion freshness, memory, and restart/OOM history.
6. If the first replica passes, add the second updated replica. Verify that
   same-type contention produces bounded `skipped_busy` events, not duplicate
   rows, integrity errors, or growing backlog. Different summary types may run
   independently. Restore only explicitly approved maintenance workers using
   the same coordinated implementation; do not reintroduce legacy writers.
7. Verify the saved desired replica/configuration state, then complete a
   representative soak. Record source identity, observations, and rollback
   readiness in a private stage-gate receipt.

Lock contention is skipped, not queued. PostgreSQL sessions must use READ
COMMITTED. Refreshes require clean, non-nested sessions. SQLite is only the
single-writer development backend; its unit tests do not prove replica safety.
Advisory locks are cooperative: an old writer or direct SQL writer can bypass
them. Each aggregation has a statement snapshot; the three summary types are
not a single atomic cross-table generation.

## Stop and rollback criteria

Stop promotion for any duplicate logical summary, integrity error, stale
summary across repeated expected cycles, new restart/OOM, unauthorized setting
change, missing actionable source-event evaluations, or loss of ingestion
freshness. Treat an API probe exceeding the previously observed 15-second
failure boundary as an immediate rollback signal. Set tighter latency, memory,
freshness and soak thresholds from the fresh preflight baseline before approval;
do not infer production SLOs from the short read-only diagnostic.

Rollback must also avoid mixed writers: stop newly introduced maintenance
writers, terminate new API replicas, verify writer transactions drained, then
restore the saved immutable image and approved replica/configuration state.
Observe repeated refreshes and ingestion afterward. Do not drop tables,
downgrade migrations, restore stale database contents, purge history, or enable
remediation as part of rollback. The old image's known limitations remain.

## Evidence and remaining limits

Local tests cover atomic reader visibility, interrupted publication, empty and
populated-table races, nonblocking contention, fresh subsequent evidence,
per-type ownership, and release on commit, rollback, cancellation, session close,
and lock timeout. PostgreSQL 15 and 16 synthetic tests passed. These are not
production lifecycle, sustained-load, mixed-version, or crash/partition tests.

The original production timeout is not yet proven fixed. Full startup can
perform real background work: a write-capable canary requires separate scope
and approval. The earlier read-only canary tested the pre-ownership SQL change;
it does not promote this changed image. Keep auto-remediation off throughout.
