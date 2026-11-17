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
  "source": {"jira": "ok|unconfigured|error", "verification": "snapshot|none",
             "verification_at": "ISO8601|null"},
  "summary": {"tickets":0,"closed":0,"closed_pct":0,"in_progress":0,"new":0,
              "unassigned":0,"verified_live":0,"live_locations":0,
              "untracked_live":0,"providers":0},
  "providers": [{"provider":"AWS","tickets":0,"closed":0,"in_progress":0,
                 "new":0,"unassigned":0,"closed_pct":0,"verified_live":0,
                 "live_locations":0,"untracked_live":0}],
  "trend": [{"date":"YYYY-MM-DD","tickets":0,"closed":0,"in_progress":0,
             "new":0,"unassigned":0,"verified_live":0,"untracked_live":0}],
  "links": [{"label":"Progress spreadsheet","url":"https://docs.google.com/..."}]
}
```

Ordering: providers by `tickets` desc, then provider name. Trend ascending by date.
Links come from `STARGATE_ROTATION_LINKS` (JSON list); absent configuration
returns `[]`. The page only renders them — Drive permissions are Google's.

`publish_rotation_snapshot.py` is the daily ingest step: it maps the audit's
raw provider names through the same buckets and posts the result. See
`DAILY-AUDIT.md`.

`GET /dashboard/rotation/provider?name=<provider>`

```json
{
  "provider": "AWS",
  "counts": {"tickets":0,"closed":0,"in_progress":0,"new":0,"unassigned":0},
  "audit": {"verified_live":0,"live_locations":0,"untracked_live":0},
  "credential_counts": {"total":0,"ticketed":0,"untracked":0},
  "credentials": [{"id":"sha256[:16]","credential":"...","live_copies":0,
                   "clusters":"...","example_location":"...","coverage":"in-jira",
                   "jira_keys":"..."}],
  "jira_url": "https://.../issues/?jql=key%20in%20(...)|null",
  "tickets": [{"key":"GPTEINFRA-1","summary":"...","status":"In Progress",
               "assignee":"...","url":"https://.../browse/GPTEINFRA-1"}]
}
```

- `name` is a query parameter so provider names containing `/`
  (`OpenShift / SA tokens`) are addressable
- 404 for a provider with neither tickets nor an audit row
- tickets ordered action-first: In Progress, New, Closed, then key
- `audit` is `null` when only tickets exist
- `jira_url` is a precise `key in (...)` filter, so it opens exactly these tickets
- `source.verification_at` is when the audit last wrote the verified fields,
  not when Jira synced
- reads stored tickets, never Jira, so it cannot disagree with the table

`POST /integration/rotation-credentials` (admin key required)

```json
{"date":"YYYY-MM-DD","credentials":[
  {"id":"sha256[:16]","credential":"aws.assume_role","provider":"AWS",
   "live_copies":87,"clusters":"...","example_location":"ns/obj:key",
   "coverage":"in-jira","jira_keys":"GPTEINFRA-18545"}]}
```

- 201 `{"date":"...","credentials":<n>}`, 403 without the admin key
- upsert per `(date, credential_id)`; values are never accepted — the id is a hash
- a credential with a ticket inherits that ticket's provider; only untracked
  credentials fall back to name-based bucketing
- provider totals (`verified_live`, `live_locations`, `untracked_live`) are
  **derived from these rows**, so a provider row and its credential list cannot
  disagree; providers with no credentials on a run are zeroed

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
- `verified_at` is stamped on every ingest row — the page shows it separately
  from the Jira sync time

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
- ticket upsert: update in place, prune tickets that left the epic, ignore the epic row
- provider detail: action-first ordering, 404 for unknown, audit-only provider opens
- credential ingest: admin-only, upsert, ticket-driven provider, name fallback
- provider taxonomy: a second parenthetical (`(sandbox-api-configs) (AWS / Route 53)`),
  nested groups, priority-only labels → `Provider unset`, two providers → `Multiple providers`

## Non-goals

- StarGate does not hold or test customer cloud/SaaS credentials; verification is
  ingested from the admin-run audit, not performed at runtime.
- No writes to Jira. The epic stays the source of truth for planning.
