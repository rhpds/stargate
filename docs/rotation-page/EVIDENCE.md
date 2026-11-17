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

Sync (`tests/test_rotation_sync.py`, 11):
provider parsing including the nested `(OCP SA Token (infra02))`, `(AI / MaaS /
Lightspeed — upstream unverified)` and no-parenthetical → `Unclassified`;
parent epic excluded; status/unassigned counts; provider ordering; two-page
pagination merged.

API (`tests/test_rotation_api.py`, 6):
explicit empty payload; latest-day-only totals (never summed across days);
ascending per-day trend; admin key required; ingest writes verified fields and
creates unknown providers empty; ingest idempotent.

Page (`frontend/src/__tests__/pages/Rotation.test.tsx`, 5):
empty state is explicit; Jira + audit numbers render together and the untracked
gap is named; trend renders at two snapshots; a single snapshot is explained
rather than drawn; a failed load is surfaced.

## Still red

**G6 Live.** Requires the deploy: `alembic upgrade head`, one Jira sync, then
`GET /dashboard/rotation` with `source.jira = "ok"` and non-zero totals, and the
page at `/rotation` showing the same numbers.
