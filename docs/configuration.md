# StarGate Configuration Reference

All configuration is via environment variables. No configuration files are
required beyond the YAML rubrics in `rubrics/platform/`.

---

## Database

### STARGATE_DATABASE_URL

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `postgresql://stargate:stargate@localhost:5432/stargate`    |
| Description | SQLAlchemy database URL for the PostgreSQL connection       |
| When to change | Always set in production. Change when the database host, port, credentials, or database name differ from the default. For local development with podman-compose, the default works out of the box. |

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

---

## Authentication

### STARGATE_ADMIN_API_KEY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `""` (empty string -- authentication disabled)              |
| Description | API key required for admin endpoints (scheduler, evidence source, dry-run, feedback) |
| When to change | Must be set in production. When empty, all admin endpoints are open. The key is sent via the `X-API-Key` HTTP header. Requests from allowed CORS origins bypass the key check for browser-based dashboard access. |

Generated during deployment by `deploy-infra01.sh` using `openssl rand -hex 24`
and stored in the `stargate-secrets` OpenShift secret as `admin-api-key`.

---

## SSL

### STARGATE_SSL_VERIFY

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `false`                                                     |
| Description | Whether to verify SSL certificates for outbound HTTPS calls (LLM, Labagator, Demolition) |
| When to change | Set to `true` in environments with proper CA certificates. Leave as `false` when connecting to internal OpenShift routes with self-signed or wildcard certificates, which is the common case for the RHDP infrastructure. |

When `false`, both hostname checking and certificate verification are disabled
for all outbound connections from the API (LLM calls, Labagator fetches,
Demolition fetches) and from scanner workers (showroom health checks).

---

## CORS

### STARGATE_CORS_ORIGINS

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | `http://localhost:3000,http://localhost:8090`                |
| Description | Comma-separated list of allowed CORS origins                |
| When to change | Must be updated for production to include the dashboard URL (e.g., `https://stargate.apps.cluster.example.com`). Add any additional origins that need to access the API from a browser. |

CORS middleware allows credentials, GET/POST methods, and the headers
`Content-Type`, `X-API-Key`, and `X-Request-ID`. The allowed origins list
also controls which browser origins can bypass API key authentication for
admin endpoints.

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
| Description | Specifies which cluster/namespace to target for gated execution (Phase C and beyond) |
| When to change | Set when enabling Phase C real-namespace execution. Value should identify the target cluster endpoint. Used in conjunction with `STARGATE_EXECUTOR_KUBECONFIG` and `STARGATE_TEST_NAMESPACE`. |

### STARGATE_EXECUTOR_KUBECONFIG

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set                                                     |
| Description | Path to the kubeconfig file for the executor service account |
| When to change | Must be set for Phase C and Phase D execution. Points to the kubeconfig for the `stargate-executor` service account which has namespace-scoped write access to the test namespace. The service account should have only the minimum permissions needed (create, scale, delete in the target namespace). |

Example: `secrets/kubeconfig-executor`

### STARGATE_TEST_NAMESPACE

| Property    | Value                                                      |
|-------------|-------------------------------------------------------------|
| Default     | Not set                                                     |
| Description | Namespace used for Phase C real-cluster testing              |
| When to change | Set to the test namespace name when running Phase C gate tests. The namespace must exist on the target cluster and the executor service account must have write access to it. |

Production value: `stargate-test` on `ocpv-infra01`.

---

## Additional LLM Cost Configuration

These variables are used internally for cost estimation in LLM metrics.

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

## Configuration Summary

| Variable                         | Default                                    | Required |
|----------------------------------|--------------------------------------------|----------|
| `STARGATE_DATABASE_URL`          | `postgresql://stargate:stargate@localhost:5432/stargate` | Yes (prod) |
| `STARGATE_LITELLM_API_KEY`       | `""`                                       | Yes (LLM) |
| `STARGATE_LITELLM_URL`           | LiteLLM prod URL                           | No       |
| `STARGATE_LLM_MODEL`             | `granite-3-2-8b-instruct`                  | No       |
| `STARGATE_ADMIN_API_KEY`         | `""`                                       | Yes (prod) |
| `STARGATE_SSL_VERIFY`            | `false`                                    | No       |
| `STARGATE_CORS_ORIGINS`          | `http://localhost:3000,http://localhost:8090` | Yes (prod) |
| `STARGATE_EVENT_DATE`            | `""`                                       | No       |
| `STARGATE_EVENT_NAME`            | `Platform Operations`                      | No       |
| `STARGATE_EVENT_PREFIX`          | `""`                                       | No       |
| `STARGATE_EVIDENCE_SOURCE`       | `real`                                     | No       |
| `STARGATE_DRY_RUN`               | `false`                                    | No       |
| `STARGATE_CONFIDENCE_THRESHOLD`  | `0.8`                                      | No       |
| `STARGATE_EXECUTION_TARGET`      | Not set                                    | Phase C+ |
| `STARGATE_EXECUTOR_KUBECONFIG`   | Not set                                    | Phase C+ |
| `STARGATE_TEST_NAMESPACE`        | Not set                                    | Phase C+ |

"Required" column indicates:
- **Yes (prod)**: Must be set in production deployments
- **Yes (LLM)**: Must be set for LLM features to function
- **No**: Has a sensible default for all environments
- **Phase C+**: Only needed for gated execution Phase C and beyond
