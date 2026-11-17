# Rotation page — evidence rubric

Each gate is RED until its evidence exists, AMBER when partial, GREEN when the
evidence is attached to the PR. A gate cannot be skipped; it can only be red.

| Gate | Question | Evidence required | State |
|---|---|---|---|
| G1 Contract | Is the schema/API fixed before code? | `CONTRACT.md` + failing tests that encode it | **GREEN** — contract committed; both test files written and observed red first |
| G2 Unit (TDD) | Do the pure rules have cases? | provider parse, aggregation, pagination, unassigned | **GREEN** — `tests/test_rotation_sync.py`, 11 passed |
| G3 Behaviour (BDD) | Do the page-level behaviours hold? | empty state, totals, ingest side-by-side, trend | **GREEN** — `frontend/src/__tests__/pages/Rotation.test.tsx`, 5 passed |
| G4 Contract API | Do the endpoints obey the shapes and auth? | 200 shape, 403 without key, 201 ingest, idempotency | **GREEN** — `tests/test_rotation_api.py`, 6 passed |
| G5 Evidence (EDD) | Is the red→green transition recorded? | red run captured, green run captured, receipt JSON | **GREEN** — `test-receipts/rotation-page-2026-11-17.json` |
| G6 Live | Does it show real numbers in production? | endpoint output + deployed page | **RED** — pending deploy, `alembic upgrade head`, one Jira sync |
| G7 Non-regression | Did anything else break? | full suite + ruff + tsc + frontend tests | **GREEN** — 2459 passed; ruff clean; tsc clean; 24 frontend tests; build ok |
| G8 Ops | Can it be re-run and trusted? | sync loop, last_sync surfaced, ingest documented | **GREEN** — 30-min loop gated by `STARGATE_ROTATION_SYNC_ENABLED`; `last_sync` in payload; contract documents ingest |

**AMBER** = implementation exists but the evidence is not attached.
**GREEN** = evidence attached in the PR and reproducible by a second person.

## Red → green, as run

RED (pre-implementation tree):

- `pytest tests/test_rotation_sync.py` → collection error, `cannot import name
  'rotation_sync' from 'collectors'`
- `pytest tests/test_rotation_api.py` → 6 failed (404 on both endpoints; no
  `RotationSnapshot` model)

GREEN:

- `pytest tests/test_rotation_sync.py tests/test_rotation_api.py -q` → 17 passed
- `pytest -m "not integration" -q` → 2459 passed, 17 skipped
- `ruff check .` → clean · `tsc --noEmit` → clean · `npm test` → 24 passed ·
  `npm run build` → ok

## What G6 has to show

1. `GET /dashboard/rotation` returns `source.jira = "ok"` and non-zero totals
   after one sync.
2. The page at `/rotation` renders the provider table with the same numbers.
3. `last_sync` is within one sync interval.

Until then G6 stays red, and the page shows its explicit empty state rather
than zeros pretending to be fact.
