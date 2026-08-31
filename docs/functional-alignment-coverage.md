# Functional alignment delivery status

“Implemented” means source and durable contracts exist. It does not mean the
feature is deployed or enabled. Deployment and promotion are separate decisions;
all feature gates default off until a passing receipt and canary are recorded.

| Gate | Functional status | Automated evidence | Deployment status | Promotion status |
|---|---|---|---|---|
| 0 WorkshopProvision | Implemented | Collector status, condition, empty-result, and failure fixtures | RBAC/worker changes held for separate review | Not promoted |
| 1 AAP ingestion | Implemented | Sanitization, idempotent upsert, sanitized failed-job fixture, API contract | Source committed; runtime configuration required | Disabled |
| 2 Diagnosis claims | Implemented | Claim, reopen, evidence-hash, association, and concurrency behavior | Source committed | Disabled |
| 3 Slack | Implemented behind gate | Suppression, deduplication, payload, retry, and delivery-ledger tests | Webhook secret required | Disabled |
| 4 Jira | Implemented behind approval gate | Draft, deduplication, approval, and mocked REST behavior | Service configuration required | Disabled |
| 5 Knowledge | Implemented behind review gate | Review/version/provenance and retrieval-match tests | Source committed | Disabled |
| 6 Trends | Implemented behind gate | Durable event-rate and catalog-regression threshold tests | Source committed | Disabled |

Promotion requires a persisted receipt with all critical criteria passing, score at least 90, zero severity-one defects, zero duplicates, and verified rollback.
