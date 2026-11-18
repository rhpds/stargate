# How the rotation numbers are made

The page shows two facts side by side — what Jira plans and what is actually
live — and never merges them into one number. This is the full path from a
cluster Secret to a cell in the table.

## The three sources

| Source | What it contributes | Who writes it |
|---|---|---|
| Jira epic `GPTEINFRA-18544` (label `turkeyvulture`) | the plan: tickets, status, owner | Jira is the source of truth |
| Fleet audit (read-only, admin-run) | what exists: values found live, where, how many copies | `grant-audit-access.sh` + the audit scripts |
| Progress spreadsheet (Drive) | the human-facing view of the same two facts | generated from both |

The page reads **only StarGate's database**. It never calls Jira on a page load
and never reads a Secret.

## The join keys

```
secret value ──sha256[:16]──► credential identity
ticket key  ──provider──────► provider bucket
provider bucket ────────────► the row you click
```

- **`sha256[:16]`** is the identity of a credential. The audit hashes each value
  in memory; the hash is stored, the value never is. Two clusters holding the
  same key produce the same id — that is what makes "87 copies" measurable.
- **The ticket key** (`GPTEINFRA-18547`) ties a credential to the work item that
  rotates it.
- **The provider bucket** is the only join between the two worlds: it is parsed
  from a ticket title and classified by the audit for a credential. That
  vocabulary is mapped explicitly in `PROVIDER_ALIASES` so `Quay` and
  `Registry` become one row.

## Step by step

**1. Jira sync — every 30 minutes** (`collectors/rotation_sync.py`)

- Pull every issue labelled `turkeyvulture` (paged, ~227 issues).
- Parse the provider from the **last balanced parenthetical** of the title:
  - `… Rotate x (AWS)` → `AWS`
  - `… Rotate x (OCP SA Token (infra02))` → `OpenShift / SA tokens` (nesting kept)
  - `… (sandbox-api-configs) (AWS / Route 53)` → `AWS` (only the last group)
  - `… (P1 — Bitwarden Secrets Manager)` → `Provider unset` (a priority is not a provider)
  - names two providers → `Multiple providers`
  - nothing → `Unclassified`
- Count tickets by status, count unassigned, store every ticket in
  `rotation_tickets` (so the drill-down never calls Jira), and upsert today's
  row per provider in `rotation_snapshots`.
- Providers that disappeared are pruned or zeroed — old taxonomies must not
  linger in today's totals.

**2. Fleet audit — daily, outside StarGate**

- An admin mints a two-hour, read-only `stargate-audit` token per cluster.
- The audit reads Secrets, Deployment env and AnarchySubject values, hashes each
  in memory, and matches hashes across clusters and namespaces.
- It classifies each credential to a provider: the inventory's variable →
  provider first, then keywords in the credential name, else
  `Unresolved API / token issuer`.
- Output: `credential-coverage.csv` — one row per credential id, with copies,
  clusters, example location, coverage and ticket keys.

**3. Publish — the audit's last step** (`scripts/publish_rotation_snapshot.py`)

```bash
python3 -m scripts.publish_rotation_snapshot \
    --snapshot snapshots/turkeyvulture-$(date -u +%F).json \
    --credentials-csv credential-coverage.csv
```

- Maps the audit's provider names onto the page's buckets.
- Posts the aggregate, then the 326 per-credential rows, to
  `/integration/rotation-snapshot` and `/integration/rotation-credentials`.
- Refuses to count identical evidence twice (two names for one bucket inflated
  the fleet by 4 credentials / 73 locations on 17 Nov).
- Idempotent: re-running is safe.

**4. Ingest** (`api/routers/integration.py`)

- Upserts credentials per `(day, credential id)`.
- **Derives every provider total from those rows**: `verified_live` = distinct
  ids, `live_locations` = sum of copies, `untracked_live` = ids whose coverage
  is not `in-jira`.
- Deletes rows that have neither tickets nor credentials.

**5. Read — the page** (`api/routers/dashboard/rotation.py`)

- Tickets come from **today's** row.
- Verification comes from the **most recent row that was actually audited** —
  so shortly after midnight the page shows last night's numbers with their age,
  not zeros.
- Providers are the union of both; totals are the sum of the visible rows.

**6. Trend**

One point per day, summed across providers. Nothing is interpolated: a day with
no audit has no verified number.

## What each column means

| Column | Meaning |
|---|---|
| Tickets / Closed / In progress / New | Jira status at the last sync |
| % closed | closed ÷ tickets |
| Unassigned | no assignee in Jira |
| **Verified live** | distinct credential values the audit found in clusters |
| **Locations** | every place those values appear (Secret, env var, AnarchySubject field) |
| **Untracked** | verified credentials with no resolving Jira ticket |

Tickets and credentials are **not 1:1**. One ticket may cover several values
(`aws.assumerole_aws_access_key_id` *and* its secret); one value may appear in
900 locations. That is why both columns exist.

## Worked example — AWS

- **46 tickets**, 7 closed (15%), 9 in progress, 22 unassigned → the plan.
- **50 credentials** hash-matched in the fleet, across **300 locations**.
- **3 of those 50 have no resolving ticket** → candidates to file.

The 46 and the 50 are different measurements: one counts work items, the other
counts live secrets. Neither is expected to equal the other.

## What the numbers cannot tell you

- **Provider attribution is a classification, not a fact.** The audit prefers
  the inventory's provider for the variable, then the name. Where the *issuer*
  and the *consumer* differ (an Azure service principal used by AAP) the bucket
  is a judgement. AAP's 1,427 locations are mostly that case.
- **"No ticket" is a name-and-key join.** A ticket that rotates the same value
  under a different name is not credited until the tracker carries the hash.
  227 credentials have no Jira ticket; 189 appear nowhere in the tracker at all
  — the 38 difference have an inventory row but no ticket.
- **Hash matching is exact.** A value that differs by one character or a
  trailing newline is a different credential.
- **Unreadable is not absent.** A credential the audit's grant could not read is
  not counted, rather than counted as dead.
- **The page never holds a value.** Every credential is an id and a count.

## Where the code is

- `collectors/rotation_sync.py` — Jira pull, provider parsing, ticket storage
- `scripts/publish_rotation_snapshot.py` — the audit's publish step
- `api/routers/integration.py` — ingest and derivation of provider totals
- `api/routers/dashboard/rotation.py` — the read model behind the page
- `frontend/src/pages/Rotation.tsx` — the page
- `docs/rotation-page/DAILY-AUDIT.md` — cadence and operating notes
