# Functional alignment coverage matrix

| Gate | Unit/TDD | Evidence/EDD | Contract/CDD | Behavior/BDD | Component/CBT | Promotion default |
|---|---|---|---|---|---|---|
| 0 WorkshopProvision | collector status/class tests | CRD condition fixtures | snapshot query-health shape | failure vs empty scenarios | live worker + DB snapshot | blocked on Babylon RBAC/stability |
| 1 AAP ingestion | sanitization/upsert tests | sanitized failed-job fixture | source-event contract | repeated collection | SQLite/Postgres migration | disabled |
| 2 Diagnosis claims | claim/reopen tests | evidence hashes | investigation source links | two competing workers | repository lifecycle | disabled |
| 3 Slack | suppression/dedup tests | enriched finding payload | notification ledger | retry/restart | mocked HTTP delivery | disabled |
| 4 Jira | draft/approval tests | reviewed diagnosis | REST adapter payload | approval required | mocked Jira REST | disabled |
| 5 Knowledge | review/version tests | approved diagnosis | provenance/version shape | correction retires prior | retrieval match | disabled |
| 6 Trends | threshold tests | durable success/failure events | trend signal shape | regression/rate increase | routed evaluation/investigation | disabled |

Promotion requires a persisted receipt with all critical criteria passing, score at least 90, zero severity-one defects, zero duplicates, and verified rollback.
