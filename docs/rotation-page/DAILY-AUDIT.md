# Daily audit → ingest

The rotation page has two inputs, on two different clocks:

| Input | Cadence | Who writes it |
|---|---|---|
| Ticket counts | every 30 min | `collectors/rotation_sync.py` in the API pod |
| Verified-live counts | **daily** | the fleet audit, via `scripts/publish_rotation_snapshot.py` |

Daily is deliberate. Credentials do not rotate hourly, and the trend is daily —
a more frequent audit writes identical rows and buys nothing, while a standing
cluster-wide secret reader is exactly the exposure this programme is removing.

## The sequence

1. Run the fleet audit under the time-boxed grant (`grant-audit-access.sh`
   mints a 2-hour `stargate-audit` token per cluster; `revoke-audit-access.sh`
   removes it). The audit hashes in memory and writes
   `snapshots/turkeyvulture-YYYY-MM-DD.json` — counts and hashes, never values.
2. Publish it as the last step of the run:

```bash
export STARGATE_API_URL=https://stargate-api.apps.ocpv-infra01.dal12.infra.demo.redhat.com
export STARGATE_ADMIN_API_KEY=...   # from stargate-secrets:admin-api-key

python3 -m scripts.publish_rotation_snapshot \
    --snapshot snapshots/turkeyvulture-$(date -u +%F).json \
    --credentials-csv credential-classification.csv
```

`--credentials-csv` is optional but enables the per-credential view (which
credential, how many copies, ticketed or not). It accepts either
`credential-classification.csv` or `jira-coverage.csv`.

`--dry-run` prints the exact payload without posting.

## What the publisher does

- collapses the audit's long-tail provider names into the same buckets Jira
  uses (`P1 — AWS; DNS/Route 53…` → `AWS`), so one provider is one row
- drops rows with no evidence — an ingest never creates an empty provider
- posts to `POST /integration/rotation-snapshot`, which upserts per
  `(date, provider)` and never touches the Jira counters
- posts the per-credential rows after the aggregate, and the server re-derives
  every provider total from them — the aggregate is a fallback, not the truth
- refuses to count the same evidence twice: if two raw names collapse into one
  bucket with identical `(verified, locations, untracked)`, it logs and counts
  once. On 2026-11-17 that corrected the fleet from 153/1,829/72 to
  **149/1,756/71** — `Storage` and `Datastores` were two names for one bucket

Re-running is safe: the endpoint is idempotent, so a failed post can simply be
repeated.

## If it does not run

The page keeps the last snapshot and shows its timestamp. It does not zero the
verified columns — absence of evidence is not evidence of rotation.

## Source links

The page can link to wherever the working data lives (Sheets, Drive, the
classification pack). Configure, do not hardcode:

```
STARGATE_ROTATION_LINKS=[{"label":"Progress spreadsheet (Google Sheets)","url":"https://docs.google.com/spreadsheets/d/<id>/edit"}]
```

Drive permissions are enforced by Google; the page only renders the link.
