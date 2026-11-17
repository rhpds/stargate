# Rotation page — evidence (red → green)

Machine receipt: `test-receipts/rotation-page-2026-11-17.json` (local by
convention — `test-receipts/*.json` is gitignored). This file is the tracked
copy of the evidence the rubric points at.

## RED — before implementation

Reproduced by moving the new implementation files aside and stashing the
tracked edits, so the tree matches its pre-implementation state.

```
$ .venv/bin/python -m pytest tests/test_rotation_sync.py -q
ERROR tests/test_rotation_sync.py
E   ImportError: cannot import name 'rotation_sync' from 'collectors'

$ .venv/bin/python -m pytest tests/test_rotation_api.py -q
6 failed
  test_empty_state_is_explicit              404 /dashboard/rotation
  test_latest_day_only_and_totals           404 /dashboard/rotation
  test_trend_is_ascending_and_per_day       404 /dashboard/rotation
  test_requires_admin_key                   404 /integration/rotation-snapshot
  test_ingest_writes_verified_fields        404 /integration/rotation-snapshot
  test_ingest_is_idempotent                 404 /integration/rotation-snapshot
```

## GREEN — after implementation

```
$ .venv/bin/python -m pytest tests/test_rotation_sync.py tests/test_rotation_api.py -q
17 passed

$ .venv/bin/python -m pytest -m "not integration" -q
2459 passed, 17 skipped, 15 deselected

$ .venv/bin/python -m ruff check .
All checks passed!

$ npx tsc --noEmit
(clean)

$ npm test
4 test files, 24 tests passed

$ npm run build
built in 202ms
```

## Cases pinned

Sync (`tests/test_rotation_sync.py`, 22):
provider parsing including the nested `(OCP SA Token (infra02))`, `(AI / MaaS /
Lightspeed — upstream unverified)` and no-parenthetical → `Unclassified`;
parent epic excluded; status/unassigned counts; provider ordering; two-page
pagination merged; ticket upsert updates in place and prunes tickets that left
the epic; the parent epic is never stored.

API (`tests/test_rotation_api.py`, 12):
explicit empty payload; latest-day-only totals (never summed across days);
ascending per-day trend; admin key required; ingest writes verified fields and
creates unknown providers empty; ingest idempotent; source links from config,
empty by default, malformed ignored; provider detail action-first ordering, 404
for unknown, audit-only provider opens.

Page (`frontend/src/__tests__/pages/Rotation.test.tsx`, 9):
empty state is explicit; Jira + audit numbers render together and the untracked
gap is named; trend renders at two snapshots; a single snapshot is explained
rather than drawn; a provider row opens into its tickets and closes again; the
source-data link renders only when configured; a failed load is surfaced.

## Live — 2026-11-17

Deployed as PRs #110 and #111; migration `m4b5c6d7e8f9` applied at startup.

```
GET /dashboard/rotation
  source     jira=ok, verification=snapshot
  summary    226 tickets, 85 closed (38%), 16 in progress, 125 new,
             91 unassigned, 153 verified live, 1,829 locations,
             72 untracked live, 45 providers
  last_sync  2026-11-17T22:30:36Z
  trend      1 point (2026-11-17)
```

Scheduled loop observed: `Rotation sync: 227 issues → 45 providers for
2026-11-17`. The audit snapshot for the day was ingested via
`POST /integration/rotation-snapshot` (17 providers, 153/1,829/72).

Frontend pod serves `assets/index-Cl2mTKIU.js` — the bundle from the merge
commit, containing the Rotation page and its `/dashboard/rotation` call.

## Found live

The first production sync hung in Jira pagination: `_fetch_page` accepted
`nextPageToken` and never sent it, so page 1 repeated forever. The unit tests
stubbed `_fetch_page`, so they passed. Fixed in #111 and covered by two new
tests. The loop was turned off in production until the fixed image was rolled
out — the page kept serving its last snapshot, which is the intended failure
mode.

## Publisher (`tests/test_publish_rotation_snapshot.py`, 6)

Raw audit names collapse into page buckets, rows with no evidence are dropped,
distinct buckets stay separate, the admin key reaches the request, a missing
key fails before any request, and a non-snapshot file is rejected.
