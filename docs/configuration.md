# StarGate Configuration Reference

All configuration is via environment variables. No configuration files are
required beyond the YAML rubrics in `rubrics/platform/`.

---

## Database

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
| Default     | `50`                                                        |
| Description | Maximum total investigations per day                        |

### STARGATE_INVESTIGATE_MAX_STUCK_PER_DAY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `100`                                                       |
| Description | Maximum stuck-namespace investigations per day              |

### STARGATE_INVESTIGATE_MAX_ANOMALOUS_PER_DAY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `50`                                                        |
| Description | Maximum anomalous-namespace investigations per day          |

### STARGATE_INVESTIGATE_MAX_PER_CATALOG_HOUR

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `3`                                                         |
| Description | Maximum investigations per catalog item per hour (rate limit) |

### STARGATE_INVESTIGATE_DEDUP_HOURS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `4`                                                         |
| Description | Hours to deduplicate investigations for the same lab+failure_class |

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
| `STARGATE_INVESTIGATE_MAX_PER_DAY`       | `50`                    | No          |
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

"Required" column indicates:
- **Yes (prod)**: Must be set in production deployments
- **Yes (LLM)**: Must be set for LLM features to function
- **No**: Has a sensible default for all environments
- **Proof/Exec**: Only needed for proof system and remediation execution
