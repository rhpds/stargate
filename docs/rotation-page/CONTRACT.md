# Rotation page — contract (CDD)

**Purpose.** One page that shows the Turkey Vulture rotation as two truths side
by side: what Jira says the plan is, and what is actually live in the clusters.
Where they disagree, the page says so.

## Data model

`rotation_snapshots` — one row per (day, provider).

| column | type | notes |
|---|---|---|
| id | serial | PK |
| snapshot_date | date | indexed; part of the unique key |
| provider | varchar(80) | canonical bucket |
| tickets | int | child tickets in the epic for this provider |
| closed | int | Jira status Closed |
| in_progress | int | Jira status In Progress |
| new | int | Jira status New |
| unassigned | int | tickets with no assignee |
| verified_live | int | distinct values hash-matched live (ingest) |
| live_locations | int | every live location of those values (ingest) |
| untracked_live | int | live credentials with no ticket (ingest) |
| synced_at | timestamptz | when the Jira pull wrote the row |

Unique: `(snapshot_date, provider)`.

## Endpoints

`GET /dashboard/rotation`

```json
{
  "generated_at": "ISO8601",
  "last_sync": "ISO8601|null",
  "source": {"jira": "ok|unconfigured|error", "verification": "snapshot|none"},
  "summary": {"tickets":0,"closed":0,"closed_pct":0,"in_progress":0,"new":0,
              "unassigned":0,"verified_live":0,"live_locations":0,
              "untracked_live":0,"providers":0},
  "providers": [{"provider":"AWS","tickets":0,"closed":0,"in_progress":0,
                 "new":0,"unassigned":0,"closed_pct":0,"verified_live":0,
                 "live_locations":0,"untracked_live":0}],
  "trend": [{"date":"YYYY-MM-DD","tickets":0,"closed":0,"in_progress":0,
             "new":0,"unassigned":0,"verified_live":0,"untracked_live":0}]
}
```

Ordering: providers by `tickets` desc, then provider name. Trend ascending by date.

`POST /integration/rotation-snapshot` (admin key required)

```json
{"date":"YYYY-MM-DD","providers":[{"provider":"AWS","verified_live":50,
  "live_locations":300,"untracked_live":21}]}
```

- 201 `{"date":"...","providers":<n>}`
- 403 without admin key
- unknown provider creates the row with ticket counters at 0 (it will be filled
  by the next Jira sync)
- idempotent: re-posting the same date/provider overwrites the verified fields

## Behaviours (BDD)

1. No data yet → `summary.providers == 0`, `source.jira == "unconfigured"`, page
   renders an explicit empty state (not zeros pretending to be fact).
2. After a Jira sync → providers ordered by ticket count; totals are the sum of
   the latest day only, never across days.
3. After an ingest → verified fields appear next to ticket fields; `untracked_live`
   is shown even when there is no ticket for that provider.
4. Trend → one point per day, ascending; a single day is valid output.
5. Ingest without the admin key → 403, no row written.

## Cases (CBT)

- provider parsing: `(AWS)`, nested `(OCP SA Token (infra02))`,
  `(AI / MaaS / Lightspeed — upstream unverified)`, no parenthetical → Unclassified
- the parent epic ticket is excluded from counts
- pagination across two Jira pages
- unassigned counting
- upsert idempotency for both sync and ingest
- ingest for an unknown provider

## Non-goals

- StarGate does not hold or test customer cloud/SaaS credentials; verification is
  ingested from the admin-run audit, not performed at runtime.
- No writes to Jira. The epic stays the source of truth for planning.
