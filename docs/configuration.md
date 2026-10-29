# StarGate Configuration Reference

All configuration is via environment variables. No configuration files are
required beyond the YAML rubrics in `rubrics/platform/`.

---

## API reliability and metrics

HTTP metric `path` labels use registered route templates (for example,
`/runs/{run_id}`), not individual resource IDs. Unmatched requests share
`<unmatched>` and nonstandard HTTP methods share `OTHER`. This bounds metric
cardinality, prevents per-ID series retention in API memory, and avoids
resource identifiers in exported metric labels. Raw paths remain in request
logs for diagnostics. Update monitoring queries that relied on concrete
resource paths to use the route template instead. A rollout clears retained
old per-resource series in each process; counters reset as with any restart.

Request schema types must be imported at module scope and resolved before route
registration, including rate-limited handlers. OpenAPI generation and the
non-executing remediation preview are regression-tested. Neither schema
validation nor preview is proof of recovery or permission to execute a fix.

Memory allocation diagnostics identified growing Prometheus allocations with
raw-path labels; this is an addressed source of unbounded retention, not proof
that all memory growth is resolved. Check RSS, new OOMs, metric-label stability,
and ingestion health through a representative soak after deployment. Keep
dry-run enabled and model configurations unchanged while validating API repairs.

## Database

### Operations query windows and baseline cache

The lifecycle matrix uses the last hour of evaluations for current failures.
Its historical attention baseline uses seven days of evaluations. These are
different windows: reducing the baseline to one day favors recent behavior but
gives fewer samples for rare failures and makes attention labels more volatile.
It does not replace indexing or reuse of the baseline calculation.

Lifecycle and remediation-strategy requests share the existing one-hour-TTL
baseline cache. Refreshes are serialized per API process so concurrent requests
do not rebuild the same history simultaneously. Each replica has its own cache.
A cold cache still needs an initial baseline query. A failed refresh raises
rather than replacing the prior data with an empty/healthy-looking baseline.
The cache does not change model configuration or enable investigation/execution.

Optional Labagator display titles are read from the API's existing metadata
cache, populated by startup/other collectors. Lifecycle requests never wait
for a live metadata request; stored names/catalog identifiers remain usable
when metadata is absent or stale. This changes labels only, not failure data.
The investigations list batches latest evaluation, first-observation, and linked
resolution lookups for the displayed records rather than performing historical
queries per investigation. It retains the existing latest-ID and status rules
and projects only the evaluation columns needed for list status.

Migration `g7b8c9d0e1f2` adds `idx_eval_evaluated_at` to support evaluation time
filters. PostgreSQL creates/drops it concurrently outside a transaction. Normal
writes remain possible, but building an index consumes I/O and disk headroom;
check capacity and observe the build before promotion. An existing index must
be valid, ready, nonunique, and match the intended table/column. Invalid or
mismatched builds require inspection rather than silently proceeding. Retain
the additive index when reverting application behavior; do not run a destructive
database downgrade just to roll back caching. A rollback image must retain the
migration revision so startup migration discovery still recognizes the database.

Migration `h8c9d0e1f2a3` adds two matching history indexes:
`(lab_code, evaluated_at)` for all-time first observation, and
`(lab_code, failure_class, id)` for the latest evaluation ID. The read helpers
probe only the requested namespaces/pairs in one SQL statement instead of
grouping all their historical rows. Late-arriving records retain latest-ID
semantics; first observation is not truncated to the baseline window. Lifecycle
display metadata selects only the columns it uses, not full mapping objects.
Build these indexes sequentially and concurrently on PostgreSQL after checking
disk headroom. They add storage and write-maintenance cost but do not delete
history or change collection frequency. Retain both migration revisions in any
rollback image; leave additive indexes in place when reverting application code.

Verify cold and repeat endpoint latency, production ingestion, replica memory,
and dry-run gates after rollout. Faster repeat responses do not prove that every
Operations tab or a user's full browser session has been measured.

### STARGATE_DATABASE_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | SQLAlchemy database URL for the PostgreSQL connection       |
| When to change | Must be set in production. For local development with podman-compose, set to `postgresql://stargate:changeme@localhost:5432/stargate`. |

The connection pool is configured with `pool_size=20`, `max_overflow=10`,
`pool_pre_ping=True`, and `pool_recycle=3600` (1 hour). These values are
hardcoded in `db/database.py` and require a code change to modify.

Example for OpenShift:

```
STARGATE_DATABASE_URL=postgresql://stargate:$(PG_PASSWORD)@stargate-postgres:5432/stargate
```

---

## LLM

### STARGATE_LITELLM_API_KEY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Bearer token for the LiteLLM proxy API                      |
| When to change | Must be set for any LLM features to work (classification, remediation, executive summaries). Obtain from the LiteLLM admin. If not set, a warning is logged at startup and all LLM calls will fail. |

Stored in the `stargate-secrets` OpenShift secret as `litellm-api-key`.

### STARGATE_LITELLM_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `https://litellm.example.com/v1/chat/completions` |
| Description | Full URL to the LiteLLM chat completions endpoint           |
| When to change | Change when pointing to a different LiteLLM instance, a local model server, or any OpenAI-compatible API. The URL must end with the completions path. |

### STARGATE_LLM_MODEL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `granite-3-2-8b-instruct`                                  |
| Description | Model name passed to LiteLLM in the `model` field           |
| When to change | Change when switching to a different model (e.g., `granite-3-2-3b-instruct` for lower latency, or a different model family). The name must match what the LiteLLM proxy expects. |

### STARGATE_AUTO_LLM

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `true`                                                      |
| Description | Enable automatic LLM classification of unrecognized failures |
| When to change | Set to `false` to disable auto-classification. When enabled, unrecognized failures are sent to the LLM for classification proposals. |

### STARGATE_LLM_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Alternative LLM endpoint for proof system explanations       |
| When to change | Set when using a separate LLM endpoint for proof/remediation explanations vs the main LiteLLM proxy. |

### STARGATE_LLM_API_KEY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | API key for the alternative LLM endpoint (STARGATE_LLM_URL) |
| When to change | Set alongside STARGATE_LLM_URL when using a separate LLM endpoint. |

### STARGATE_LLM_COST_PROMPT

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `0.003`                                                     |
| Description | Cost per 1,000 prompt tokens in USD                         |
| When to change | Update when the model pricing changes or when using a different model with different pricing. |

### STARGATE_LLM_COST_COMPLETION

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `0.006`                                                     |
| Description | Cost per 1,000 completion tokens in USD                     |
| When to change | Update when the model pricing changes or when using a different model with different pricing. |

---

## Authentication

### STARGATE_ADMIN_API_KEY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string -- all admin requests rejected with 503) |
| Description | API key required for mutating admin endpoints (execute, approve, config changes, scheduler start/stop). Read-only GET endpoints also accept same-origin browser requests. |
| When to change | Must be set in production. When empty, no admin operations are possible. The key is sent via the `X-API-Key` HTTP header. |

Stored in the `stargate-secrets` OpenShift secret as `admin-api-key`.

### STARGATE_TRUST_PROXY_AUTH

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `false`                                                     |
| Description | When `true`, the `x-forwarded-user` header from a trusted proxy (e.g., OpenShift OAuth proxy) grants admin access. |
| When to change | Enable in deployments behind an OAuth proxy that sets `x-forwarded-user`. The application must only be reachable through the proxy — if directly accessible, any client can spoof this header. |

---

## SSL

### STARGATE_SSL_VERIFY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `true`                                                      |
| Description | Whether to verify SSL certificates for outbound HTTPS calls (LLM, Labagator, Demolition, Prometheus, AlertManager, AAP, ZeroTouch) |
| When to change | Set to `false` when connecting to internal OpenShift routes with self-signed or wildcard certificates. In production with proper CA certificates, leave as `true`. |

When `false`, both hostname checking and certificate verification are disabled
for all outbound connections from the API and collectors. All components
check this env var before disabling TLS.

---

## CORS

### STARGATE_CORS_ORIGINS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `http://localhost:3000,http://localhost:8090`                |
| Description | Comma-separated list of allowed CORS origins                |
| When to change | Must be updated for production to include the dashboard URL (e.g., `https://stargate.apps.cluster.example.com`). Add any additional origins that need to access the API from a browser. |

CORS middleware allows credentials, GET/POST methods, and the headers
`Content-Type`, `X-API-Key`, and `X-Request-ID`.

---

## Cluster Configuration

### STARGATE_CLUSTERS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set (uses built-in default list)                        |
| Description | Comma-separated list of cluster names to scan (e.g., `ocpv05,ocpv06,ocpv07`) |
| When to change | Set to override the default cluster list. Each cluster needs a matching kubeconfig file in `secrets/`. |

### STARGATE_CLUSTERS_FILE

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set                                                     |
| Description | Path to a JSON file containing cluster definitions with tiers and kubeconfigs |
| When to change | Set for advanced multi-tier scheduling (5m/15m/1h scan intervals per cluster). |

### STARGATE_CLUSTER_URLS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Comma-separated `cluster=url` pairs for Prometheus/Thanos endpoints |
| When to change | Set to enable infrastructure metrics collection from cluster monitoring stacks. |

### STARGATE_INCLUDE_NS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `sandbox-,launchpad-,stargate,platform-dashboard,intel-rh-,demolition-,labagator-,cost-monitor,fleetview-` |
| Description | Comma-separated namespace prefixes to include in scans      |
| When to change | Add prefixes when new namespace patterns need monitoring. |

### STARGATE_EXCLUDE_NS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `openshift-,kube-`                                          |
| Description | Comma-separated namespace prefixes to exclude from scans    |
| When to change | Add prefixes for namespaces that should never be scanned. |

### STARGATE_ECOSYSTEM_NS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `stargate,deepfield,geolux,demolition-,labagator-,cost-monitor,fleetview-` |
| Description | Comma-separated namespace prefixes for ecosystem (infrastructure) namespaces |
| When to change | Update when new ecosystem services are deployed. Ecosystem namespaces are tracked separately from user sandboxes. |

### STARGATE_REMEDIATION_NS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Same as ecosystem default                                   |
| Description | Comma-separated namespace prefixes eligible for remediation actions |
| When to change | Restrict to limit which namespaces the action executor can target. |

---

## Integration URLs

### STARGATE_DEEPFIELD_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | External Deepfield service URL for event forwarding         |
| When to change | Set when Deepfield is deployed and events should be forwarded to it. |

### STARGATE_DEEPFIELD_INTERNAL_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `http://deepfield-backend.deepfield.svc:8099`               |
| Description | In-cluster Deepfield URL for the admin proxy dashboard      |
| When to change | Change if Deepfield runs in a different namespace or on a different port. |

### STARGATE_GEOLUX_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `http://geolux-geolux.geolux.svc:8091`                     |
| Description | GeoLux governance engine URL                                |
| When to change | Change if GeoLux runs in a different namespace or port. Used for hypothesis forwarding and admin proxy. |

### STARGATE_GEOLUX_API_KEY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Falls back to `STARGATE_ADMIN_API_KEY`                      |
| Description | API key for GeoLux authentication                           |
| When to change | Set when GeoLux uses a different API key than StarGate's admin key. |

### STARGATE_ZEROTOUCH_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string — collector disabled)                    |
| Description | ZeroTouch provisioning API URL                              |
| When to change | Set to enable ZeroTouch lab data collection. |

### STARGATE_SANDBOX_API_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Sandbox API URL for placement actions (start/stop/destroy)  |
| When to change | Set to enable RHDP Sandbox API remediation actions. |

### STARGATE_SANDBOX_API_TOKEN

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Bearer token for Sandbox API authentication                 |
| When to change | Required when STARGATE_SANDBOX_API_URL is set. |

### STARGATE_SANDBOX_API_METRICS_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string — collector disabled)                    |
| Description | Sandbox API metrics endpoint for health/capacity data       |
| When to change | Set to enable Sandbox API health monitoring on the dashboard. |

### STARGATE_LABAGATOR_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Labagator API URL for lab session data                      |
| When to change | Set to enable lab identity enrichment from Labagator. |

### STARGATE_DEMOLITION_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string — collector disabled)                    |
| Description | Demolition service URL for lab lifecycle data               |
| When to change | Set to enable Demolition session data collection. |

### STARGATE_LAUNCHPAD_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Launchpad service URL for lab session lookups               |
| When to change | Set to enable Launchpad integration for session data. |

### STARGATE_LAUNCHPAD_API_KEY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | API key for Launchpad authentication                        |
| When to change | Required when STARGATE_LAUNCHPAD_URL is set. |

---

## AAP (Ansible Automation Platform)

### STARGATE_AAP_EVENT0_URL / STARGATE_AAP_EVENT1_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string — collector disabled)                    |
| Description | AAP controller URLs for job metrics collection              |
| When to change | Set to enable AAP job failure ingestion. Supports up to 2 AAP controllers (EVENT0, EVENT1). |

### STARGATE_AAP_EVENT0_USER / STARGATE_AAP_EVENT1_USER

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `monitor`                                                   |
| Description | Username for AAP controller API authentication              |

### STARGATE_AAP_EVENT0_PASS / STARGATE_AAP_EVENT1_PASS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Password for AAP controller API authentication              |

---

## Investigation Pipeline

Investigation capacity and functional delivery gates are different controls.
Budgets limit enabled investigation work; gates determine whether a durable
pipeline stage is eligible to run. Increasing a budget does not enable a gate.

### STARGATE_AUTO_INVESTIGATE

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `false`                                                     |
| Description | Enable automatic AI investigation dispatch for stuck/anomalous namespaces |
| When to change | Set to `true` to enable the investigation pipeline. When enabled, the scanner loop automatically dispatches LLM investigations for failing namespaces that meet attention classifier thresholds. |

### STARGATE_AGENT_MODEL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Falls back to `STARGATE_LLM_MODEL`                          |
| Description | Model name for investigation agent LLM calls                |
| When to change | Set to use a different (e.g., larger) model for investigations than for classification. |

### STARGATE_INVESTIGATE_MAX_PER_DAY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `200`                                                       |
| Description | Maximum total investigations per day                        |
| When to change | Set an explicit deployment value for the approved operating budget; production may override the source default. |

### STARGATE_INVESTIGATE_MAX_PER_CATALOG_HOUR

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `3`                                                         |
| Description | Maximum investigations per catalog item per hour (rate limit); set to `0` to disable |

### STARGATE_INVESTIGATE_DEDUP_HOURS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `4`                                                         |
| Description | Hours to deduplicate investigations for the same lab+failure_class |

### STARGATE_INVESTIGATE_MAX_PER_SCAN

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `10`                                                        |
| Description | Maximum investigations queued during each five-minute scan cycle |

### STARGATE_INVESTIGATE_PATTERN_DEDUP_HOURS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `2`                                                         |
| Description | Hours to reuse a representative investigation for the same catalog item, primary failure class, and cluster; set to `0` to disable |

### STARGATE_INVESTIGATE_PERSISTENT_HOURS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `4`                                                         |
| Description | Hours after which a suppressed failure class is re-investigated (persistent failure override) |

### STARGATE_INVESTIGATE_SKIP_SELF_RESOLVE_PCT

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `50`                                                        |
| Description | Skip investigation for failure classes with self-resolve rate above this percentage (learned suppression) |

### Functional-alignment gates

All gates default to `false`: `STARGATE_GATE_SOURCE_INGESTION`,
`STARGATE_GATE_DIAGNOSIS_CLAIMS`, `STARGATE_GATE_SLACK_DELIVERY`,
`STARGATE_GATE_JIRA_DRAFTING`, `STARGATE_GATE_JIRA_EXECUTION`,
`STARGATE_GATE_KNOWLEDGE_RETRIEVAL`, and `STARGATE_GATE_TREND_DETECTION`.
Enable them independently and in sequence only after recording a passing receipt
through the functional-alignment admin API. Jira execution also requires its
service URL, token, project, and issue type; Slack requires its webhook secret.

For production AAP collection, mount the `stargate-aap-controllers` Secret at
`/var/run/secrets/stargate-aap` with a `controllers.yaml` key. Each controller
entry supplies `name`, `url`, `scope: production`, and either a read-scoped
`token` or a dedicated auditor account's `username` and `password`. Keep these
values in Secrets, never in source control. The API deployment must mount this
inventory; the Babylon worker's kubeconfig mount does not provide AAP access.

With `STARGATE_GATE_SOURCE_INGESTION=true`, each API replica collects a rolling
24-hour window and waits five minutes between cycles. Pagination and durable events are uncapped;
the dashboard's `recent_failures` preview remains limited to 50. Failed jobs use
their own task events, fetched with at most eight concurrent requests per
collection. PostgreSQL transaction locks serialize each event's ledger and
evaluation writes across replicas. Recollection updates observation timestamps
without creating another evaluation for the same source event.

Collections within an API process are serialized. Job pages retain only the
fields needed by ingestion; bulky artifacts and unrelated extra variables are
discarded before accumulation. This reduces backfill allocation peaks while
preserving each failed job's task evidence; it does not establish long-term
memory stability. AAP requests share at most two TLS trust contexts (verified
and explicitly unverified) and close responses after reading, including on
decode errors. Certificate verification remains enabled by default. Trust-store
changes require an API restart to reload the shared context.

Catalog constraints use a thread-safe, 256-entry LRU cache with independent
10-minute expiry. Cache identity includes both the lab code and catalog name;
loading a new catalog cannot extend an old entry's lifetime.

For a memory investigation, set `STARGATE_MEMORY_DIAGNOSTICS=true` on the API.
It enables one-frame Python allocation tracing and logs current RSS, Python
allocation size, and Python peak allocation size every five minutes. Above
768 MiB RSS, it also logs the ten largest allocation source locations and sizes.
It never logs object contents, request bodies, or evidence. Tracing and snapshots
add overhead; use this temporarily and restart with the flag disabled after the
soak. `MALLOC_ARENA_MAX=2` can additionally limit glibc allocator arenas on Linux;
it is not an application memory cap and is read at process startup.

Validate across repeated collection cycles and a multi-day soak, checking
restarts/OOM history, production source freshness, and duplicate/missing
evaluations. Low memory immediately after a restart is not a passing soak.
Rollback uses the previous immutable API image and removes the diagnostic flag;
keep `STARGATE_DRY_RUN=true` and do not enable diagnosis or remediation as part
of memory troubleshooting.

Disable `STARGATE_GATE_SOURCE_INGESTION` to stop automatic persistence while
retaining the ledger. This gate does not enable diagnosis claims, Slack, Jira,
knowledge retrieval, trends, or automatic infrastructure remediation. An initial
backfill can use a longer collection window before returning to the rolling
24-hour schedule.

### Advisory stateless recovery pilot

`POST /admin/remediation/pilot/assess` is an authenticated, non-executing
assessment of caller-supplied evidence. It never calls a model, collects cluster
data, creates an approval, reserves an action, or invokes the executor. A passing
assessment means only `candidate_for_operator_review`; `execution_authorized`
is always false. Do not treat this response as an execution token or as measured
remediation success. Existing execution modes and global dry-run remain unchanged.

`STARGATE_STATELESS_PILOT_TARGET` is unset by default, which blocks all assessments.
If locally evaluating a hypothetical opt-in, its JSON policy requires the pinned
infra01 API server, cluster UID, `stargate-test` namespace UID, Deployment name and
UID, and accountable owner. The `cluster` policy value is restricted to `infra01`
and namespace to `stargate-test`; no production workload is opted in by this code.
Malformed policy returns a generic 503 without echoing configuration. Keep actual
deployment identities out of source control.

The v1 candidate condition is an operator-reviewed application deadlock with
evidence that a restart is appropriate, not a generic readiness failure. The
assessment requires three failed probes spanning at least five minutes, a
snapshot no older than two minutes (maximum five seconds of clock skew), a
non-Ready target pod, a matching Deployment ownership assertion, no persistent
storage, healthy dependencies/controller, no rollout/deletion, at least two
desired replicas with all other replicas Ready, and positive disruption-budget
headroom. Any confounding fault, including unknown conditions, blocks review.
Missing safety observations fail closed. The asserted incident history must have
zero prior attempts and at least one hour since any previous action, if present.

These checks test supplied assertions, not their truth: current data must later
come from trusted collectors and durable incident history. This increment does
not implement concurrent-action locking, action execution, outcome collection, or
automatic promotion. No target has been chosen or enabled. Next steps are:

1. Select an owner-approved stateless test Deployment on infra01 and independently
   verify the API/cluster/namespace/controller/pod identities and absence of
   persistent storage. Do not access excluded clusters.
2. Collect evidence through pinned read-only collectors and bind a reviewed
   diagnosis, specific action, and operator approval to the pod UID/evidence hash.
3. Add a transactional single-action claim and recheck safety after approval.
   Any future executor must use a fixed, disruption-budget-honoring action,
   never generated commands, force deletion, or automatic retries.
4. Validate in an isolated test namespace before any approved pilot execution.
   Record sustained recovery and adverse effects; recycling/self-resolution do
   not count as successful remediation. A removed pod cannot be restored as the
   same object: define replacement verification and abort/escalation rather than
   claiming an undo operation exists.

Keep auto remediation off throughout preparation. Unit/API tests demonstrate
refusal behavior, not production recovery effectiveness. The known API memory
instability must also be addressed before unattended operation.

### Review-only model adjudication

`STARGATE_ADJUDICATION_ENABLED=true` adds reviews to new successful agent
investigations with a durable investigation ID. Set
`STARGATE_ADJUDICATION_REVIEWERS` to two comma-separated distinct model IDs and
`STARGATE_ADJUDICATION_JUDGE` to a third distinct model ID. All use the existing
configured model service and credentials; configure only approved routes.

The reviewers each receive the same sanitized initial evidence and full collected
tool-result text, independently of the original diagnosis or each other's output.
The judge receives both reviews, the original diagnosis, and that same evidence.
There are no extra tools, cluster reads, or remediation actions. `ocpv06` cases
are explicitly excluded. Evidence beyond 64 KiB, original analyses beyond 16 KiB,
or insufficient worker time are held for human review, not silently truncated.

`STARGATE_ADJUDICATION_DAILY_LIMIT` defaults to 20 reservations per UTC day and
is capped at 100. A PostgreSQL transaction lock shares the reservation budget
across replicas. A unique investigation/version/evidence identity, including
the configured reviewer and judge model IDs, prevents
duplicate model calls after retries or restarts. Failed/interrupted cases consume
their reservation and are not automatically retried. Each admitted case uses at
most three calls, 900/900/1200 output tokens and 30-second timeouts. Calls run
sequentially to avoid extra parallel memory pressure. Input tokens are bounded by
the evidence-size limits but are additional to the investigation's original use.

Results are stored in `adjudications` and summarized in the finding's analysis.
The authenticated `GET /admin/functional/adjudications` endpoint returns model
provenance, evidence hash, reviews, judge, token use and review status; filter
`?status=needs_human_review` for leftovers. Running cases interrupted for more
than five minutes appear there as requiring human review. Unknown verdicts,
invalid responses, missing evidence citations and disagreements fail closed to
human review. Budget-exhausted cases are labeled in their finding and incur no
additional model calls.

Protocol `adjudication-v2.5` supplies an explicit `allowed_evidence_ids` list.
Nested evidence field names are not valid citations. Each reviewer assesses
three claims separately: observation, root cause, and remediation. Each claim
must say supported, contradicted, or unknown, cite evidence where applicable,
and identify missing evidence. A supported claim requires a citation and an
empty missing-evidence field; lack of proof is not itself a cause or a remedy.
The judge assesses those same three claims in the original diagnosis and reports
the reviewers' verdicts plus whether all three verdicts agree. Deterministic
checks independently verify that comparison and prohibit `model_supported` when
verdicts conflict, claims are unknown/contradicted, or a reviewer failed validation.

The output instruction requests one complete minified JSON object, with at most
12 words per text field, retaining all three claims. The judge receives an
explicit two-slot verdict template derived from reviewer validation, including
`INVALID` for any failed slot. These are prompt instructions, not provider-enforced
constraints or proof of model compliance. Output caps and timeouts are unchanged;
truncated or malformed responses are rejected, not repaired or automatically
retried with larger budgets. A string `"false"` is not a JSON boolean. Promotion
requires checking actual provider output; passing unit tests alone is insufficient.

Each call also requests `response_format.type=json_schema` with `strict=true`,
typed verdicts, citations, three claims, and (for judges) two verdict slots plus
a boolean agreement field. Schema support is route-specific: a proxy accepting
the parameter does not prove the backend enforces it. Local contract and evidence
checks still run; there is no fallback to unconstrained output or JSON repair.
The judge's schema additionally constrains the complete ordered verdict array to
the recorded validation facts with a single allowed array value. The judge still
assesses the incident independently; this constraint does not supply a diagnosis
or turn a failed reviewer into a valid one. Independent comparison checks remain
mandatory if the provider ignores the schema.
Structured requests explicitly request zero proxy retries (`num_retries=0`), zero
underlying-client retries (`max_retries=0`), and no fallbacks. These requests do
not prove an upstream service has no independent retry layer.
Raw HTTP template options are sent as top-level `chat_template_kwargs`.
LiteLLM may map provider extensions into its downstream client's `extra_body`;
wire shape alone does not establish forwarding or enforcement. A model may
ignore a template's thinking flag. Verify schema and reasoning controls on each
configured backend, not merely one response from a load-balanced alias. If both
standard and native schema probes are ignored, or a reasoning-only completion
exhausts its cap despite a requested sub-budget, hold promotion for provider
configuration review rather than repeatedly changing prompts or raising caps.

For DeepSeek-R1 routes the coordinator requests `thinking_token_budget=256`
within the unchanged 900-token completion cap. Backend support must be verified;
the request is not a guarantee of a reasoning limit. Usage retains
`reasoning_tokens` when reported under `completion_tokens_details`, and records
whether a separate reasoning field was present without saving that text.
Absent reasoning counts remain null. Reasoning consumes the completion allowance:
do not add its count again to completion or total tokens, or estimate tokens from
character counts. Review and judge usage metadata is retained in the adjudication
ledger even when contract validation fails. Model selection/promotion still
requires a successful bounded provider test, not just these client changes.
If any attempted call lacks reported total usage (for example after a timeout),
the adjudication's `total_tokens` is null. `models.usage_accounting.complete` is
false and `known_total_tokens` contains only the observed subtotal. This does
not establish that an upstream request stopped generating when the client timed
out; do not treat missing usage as zero or retry it automatically.

If a reviewer returns text that fails the contract, the judge may inspect that
text as explicitly unvalidated input, with `INVALID` in that reviewer's verdict
slot. This never repairs the failed review or permits acceptance. Both reviewers
failing without any returned text skips judging. Failure provenance is retained
under `models.review_validation`; the original responses remain in model metrics.
The protocol version participates in replay identity, preserving earlier results
instead of silently overwriting them after a contract revision. A schema-valid
response is not factual validation and still requires operator verification.
If a judge returns explicit verdict objects instead of strings, their verdict
values are normalized for comparison and preserved under `reviewer_verdicts_raw`.
This changes representation only; an invalid reviewer remains invalid, and a
reported raw verdict cannot stand in for its required `INVALID` validation slot.

`model_supported` means model agreement against the supplied evidence, not
verified accuracy or a successful remediation. Adjudication never changes the
operator's `review_state`, publishes knowledge, creates tickets, or enables
execution. Keep `STARGATE_DRY_RUN=true`. Disable the adjudication flag and roll
back the image to stop new reviews; retain the additive ledger and its migration
history. Historical investigations are not automatically reprocessed.

Diagnosis claims require a separate promotion. Source-bound investigations must
acquire evidence before model execution; claim errors prevent execution. Claims
record the evidence hash and lease timestamp. Expired leases are recoverable,
older owners cannot finish a newer lease, and changed evidence reopens instead
of inheriting an obsolete diagnosis or review. In-flight claims are released on
completion or failure even if the gate was disabled during the investigation.

After deployment, `/admin/functional/diagnosis-candidates` provides an admin-only,
read-only preview. It groups observations by controller, workload identity, and
operation, excludes failures followed by success or teardown, and requires fresh
collection and usable evidence. Shortened explicit provision/destroy job-name
prefixes are recognized; ambiguous identities or operations remain excluded.
The preview does not queue investigations. Its candidates still require live AAP
verification and trusted target identity before any automatic diagnosis queue is
promoted. Complete the ingestion canary before enabling the diagnosis gate.

### WorkshopProvision collection

| Variable | Default | Purpose |
|---|---|---|
| `STARGATE_WORKSHOP_PROVISION_NAMESPACES` | `babylon-catalog-prod` | Comma-separated namespaces queried by the dedicated Babylon worker |
| `STARGATE_WORKSHOP_PROVISION_STALL_HOURS` | `1` | Age threshold for stalled provision classification |
| `STARGATE_STUCK_TEARDOWN_HOURS` | `2` | Age (hours) before an AnarchySubject in destroying/destroy-failed/destroy-error is reported as `teardown_stuck` |
| `STARGATE_GAP_DEDUP_HOURS` | `24` | Gap-detection episode window: a persisting condition refreshes its evaluation inside this window and starts a new episode after it |
| `STARGATE_API_BABYLON_COLLECTION` | `false` | Enables collection inside the API process; leave false when a dedicated worker owns collection |
| `STARGATE_API_CLIENT_TIMEOUT` | `60` | Worker-to-API request timeout in seconds |

Collection credentials must be read-only and supplied by the deployment secret;
never place tokens or kubeconfig contents in values files or documentation.

### Scan snapshot retention

| Variable | Default | Purpose |
|---|---|---|
| `STARGATE_SCAN_SNAPSHOT_RETENTION_DAYS` | `7` | Number of days of database scan snapshots to retain |
| `STARGATE_SCAN_SNAPSHOT_CLEANUP_BATCH` | `1000` | Maximum rows removed in one cleanup batch |

Cleanup reclaims rows for PostgreSQL reuse. It does not shrink the physical
database file; shrinking requires a separately planned maintenance operation.

---

## AgnosticV

### STARGATE_AGNOSTICV_DIR

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Local directory containing AgnosticV repository checkout    |
| When to change | Set to enable AgnosticV constraint lookups for lab evidence enrichment. |

### STARGATE_AGNOSTICV_REPO

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `https://github.com/rhpds/agnosticv.git`                   |
| Description | Git repository URL for AgnosticV auto-clone at startup      |
| When to change | Change if using a fork or mirror of the AgnosticV repository. |

### STARGATE_AGNOSTICV_TOKEN

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | GitHub personal access token for AgnosticV repository clone |
| When to change | Required if the AgnosticV repository is private. |

---

## Event Configuration

### STARGATE_EVENT_DATE

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string -- continuous operations mode)           |
| Description | ISO date string (e.g., `2026-05-11`) targeting a specific event day |
| When to change | Set when operating in event mode to filter dashboard views and recommendations to a specific date. Leave empty for continuous monitoring without date filtering. |

### STARGATE_EVENT_NAME

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `Platform Operations`                                       |
| Description | Human-readable name displayed in dashboard headers and reports |
| When to change | Set to the event name during event operations (e.g., `Red Hat Summit 2026`). During normal operations, the default is appropriate. |

### STARGATE_EVENT_PREFIX

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string -- all pools)                            |
| Description | Pool name prefix filter (e.g., `summit-2026`)               |
| When to change | Set during event operations to filter pool and provisioning views to only event-related resources. When empty, all pools across all catalogs are included. |

---

## Evidence Source

### STARGATE_EVIDENCE_SOURCE

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `real`                                                      |
| Description | Evidence collection mode: `real` or `synthetic`             |
| When to change | Set to `synthetic` for testing with the emulator. In production, always use `real`. Can also be changed at runtime via `POST /admin/evidence-source`. |

When set to `synthetic`, evidence is generated from emulator scenarios instead
of live cluster scans. The specific scenario can be set via the admin API.

---

## Execution Control

### STARGATE_DRY_RUN

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `false`                                                     |
| Description | When `true`, the action executor logs actions but does not execute them |
| When to change | Set to `true` during initial deployment, testing, or whenever you want to observe what actions would be taken without any side effects. Audit entries are still written with status `skipped_dry_run`. Can also be toggled at runtime via `POST /admin/dry-run`. |

### STARGATE_CONFIDENCE_THRESHOLD

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `0.8`                                                       |
| Description | Minimum confidence score (0.0-1.0) for automatic action execution |
| When to change | Lower the threshold to allow more actions to execute automatically. Raise it to require higher confidence before bypassing human review. Actions below this threshold are queued to `pending_actions` for manual approval via the approval queue API. |

---

## Execution Target

### STARGATE_EXECUTION_TARGET

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set (no execution target)                               |
| Description | Specifies which cluster/namespace to target for gated execution |
| When to change | Set when enabling real-namespace execution. Value should identify the target cluster endpoint. Used in conjunction with `STARGATE_EXECUTOR_KUBECONFIG` and `STARGATE_TEST_NAMESPACE`. |

### STARGATE_EXECUTOR_KUBECONFIG

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set                                                     |
| Description | Path to the kubeconfig file for the executor service account |
| When to change | Must be set for proof system and remediation execution. Points to the kubeconfig for the `stargate-executor` service account which has namespace-scoped write access to the test namespace. |

Example: `secrets/kubeconfig-executor`

### STARGATE_TEST_NAMESPACE

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `stargate-test`                                             |
| Description | Namespace used for proof system failure injection and testing |
| When to change | Change to use a different isolated namespace for proof testing. The namespace must exist on the target cluster and the executor service account must have write access to it. |

---

## Notifications

### STARGATE_SLACK_WEBHOOK_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set (Slack notifications disabled)                      |
| Description | Slack incoming webhook URL for action notifications         |
| When to change | Set to receive Slack notifications when remediation actions are proposed, approved, or executed. |

### STARGATE_WEBHOOK_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string — disabled)                              |
| Description | Generic webhook URL for event notifications                 |
| When to change | Set to forward event notifications to an external system. |

### STARGATE_DASHBOARD_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string)                                         |
| Description | Public dashboard URL used in Slack notification links       |
| When to change | Set in production so Slack messages link back to the dashboard. |

### STARGATE_API_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `http://localhost:8090`                                      |
| Description | Internal API URL used for self-referencing API calls        |
| When to change | Set in production when the API is behind a service URL. |

---

## Cost Analysis

### STARGATE_COST_VCPU_HOUR

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `0.05`                                                      |
| Description | Cost per vCPU-hour in USD for platform cost analysis        |

### STARGATE_COST_MEMORY_GI_HOUR

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `0.01`                                                      |
| Description | Cost per GiB-hour of memory in USD                          |

### STARGATE_COST_STORAGE_GI_HOUR

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `0.0001`                                                    |
| Description | Cost per GiB-hour of storage in USD                         |

---

## Scanner

### STARGATE_INLINE_SCANNER

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `false`                                                     |
| Description | Run the scanner loop inside the API process instead of a separate worker |
| When to change | Set to `true` for single-process deployments where a separate worker pod is not available. |

---

## Configuration Summary

| Variable                                  | Default                 | Required    |
|-------------------------------------------|-------------------------|-------------|
| `STARGATE_DATABASE_URL`                   | `""`                    | Yes (prod)  |
| `STARGATE_LITELLM_API_KEY`               | `""`                    | Yes (LLM)   |
| `STARGATE_LITELLM_URL`                   | LiteLLM prod URL        | No          |
| `STARGATE_LLM_MODEL`                     | `granite-3-2-8b-instruct` | No        |
| `STARGATE_AUTO_LLM`                      | `true`                  | No          |
| `STARGATE_ADMIN_API_KEY`                 | `""`                    | Yes (prod)  |
| `STARGATE_TRUST_PROXY_AUTH`              | `false`                 | No          |
| `STARGATE_SSL_VERIFY`                    | `true`                  | No          |
| `STARGATE_CORS_ORIGINS`                  | localhost               | Yes (prod)  |
| `STARGATE_CLUSTERS`                      | built-in list           | No          |
| `STARGATE_CLUSTERS_FILE`                 | Not set                 | No          |
| `STARGATE_AUTO_INVESTIGATE`              | `false`                 | No          |
| `STARGATE_AGENT_MODEL`                   | `STARGATE_LLM_MODEL`   | No          |
| `STARGATE_INVESTIGATE_MAX_PER_DAY`       | `200`                   | No          |
| `STARGATE_DEEPFIELD_URL`                 | `""`                    | No          |
| `STARGATE_GEOLUX_URL`                    | in-cluster default      | No          |
| `STARGATE_GEOLUX_API_KEY`               | `STARGATE_ADMIN_API_KEY`| No          |
| `STARGATE_ZEROTOUCH_URL`                 | `""`                    | No          |
| `STARGATE_SANDBOX_API_URL`               | `""`                    | No          |
| `STARGATE_LABAGATOR_URL`                 | `""`                    | No          |
| `STARGATE_DEMOLITION_URL`                | `""`                    | No          |
| `STARGATE_EVENT_DATE`                    | `""`                    | No          |
| `STARGATE_EVENT_NAME`                    | `Platform Operations`   | No          |
| `STARGATE_EVIDENCE_SOURCE`               | `real`                  | No          |
| `STARGATE_DRY_RUN`                       | `false`                 | No          |
| `STARGATE_CONFIDENCE_THRESHOLD`          | `0.8`                   | No          |
| `STARGATE_EXECUTION_TARGET`              | Not set                 | Proof/Exec  |
| `STARGATE_EXECUTOR_KUBECONFIG`           | Not set                 | Proof/Exec  |
| `STARGATE_TEST_NAMESPACE`                | `stargate-test`         | No          |
| `STARGATE_SLACK_WEBHOOK_URL`             | Not set                 | No          |
| `STARGATE_COST_VCPU_HOUR`               | `0.05`                  | No          |
| `STARGATE_INLINE_SCANNER`               | `false`                 | No          |
| `STARGATE_API_BABYLON_COLLECTION`       | `false`                 | No          |
| `STARGATE_API_CORPUS_MINING`             | `false`                 | No          |

"Required" column indicates:
- **Yes (prod)**: Must be set in production deployments
- **Yes (LLM)**: Must be set for LLM features to function
- **No**: Has a sensible default for all environments
- **Proof/Exec**: Only needed for proof system and remediation execution
