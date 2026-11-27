# Helm reconciliation: what it would take, and whether to do it

Production in the `stargate` namespace is not described by the Helm release that
owns it. The release has not been applied since 2026-07-17; the Deployments have
been changed out of band ever since. This document records the size of that gap,
what an upgrade would actually do, and the three ways to close it. It does not
recommend running an upgrade.

## The release as it stands

| Field | Value |
|---|---|
| Release | `stargate`, revision 7 |
| Status | `failed` — `Upgrade "stargate" failed: context deadline exceeded` |
| First deployed | 2026-06-12 |
| Last attempt | 2026-07-17 (over four months before this document) |
| Chart version | 1.0.0 |
| Images in stored values | `:latest` for api, scanner, babylonWorker, frontend |
| `oauth.cookieSecret` | present in stored values, and nowhere else |

The `failed` status is itself a problem: `helm upgrade` on a failed release is
allowed, but `helm rollback` and `helm history` are already unreliable here, and
any tooling that treats `deployed` as a precondition will misbehave.

## What an upgrade would change today

A straight `helm upgrade` with the current chart and `values-infra01.yaml` is not
a no-op. It is a full-namespace rollout with several destructive changes.

### API Deployment

The `api` container has 51 env vars live and 31 in the chart:

| Direction | Count | Examples |
|---|---|---|
| Live only | 28 | adjudication config, AAP and GeoLux endpoints, `ROTATION_SYNC_ENABLED`, `AUTO_INVESTIGATE`, `DRY_RUN`, `EXECUTION_TARGET`, `MALLOC_ARENA_MAX` |
| Chart only | 8 | six `STARGATE_GATE_*` (all `false`), `STARGATE_JIRA_PROJECT`, `STARGATE_JIRA_ISSUE_TYPE` |
| Changed | 4 | `STARGATE_GATE_SOURCE_INGESTION` (`true` → `false`), `STARGATE_INVESTIGATE_MAX_PER_DAY` (400 → 200), `STARGATE_JIRA_URL`, `STARGATE_LITELLM_URL` |

Three of those deserve to be called out individually:

- **`STARGATE_DRY_RUN`** is dropped, and the code default is `"false"`
  (`api/routers/_shared.py`). Live is `true`. Losing the var silently turns
  remediation from a dry run into an executing one. This is the single most
  dangerous line in the diff.
- **`STARGATE_LITELLM_URL`** reverts to `https://litellm.example.com/...`.
  Every LLM call fails.
- **`STARGATE_GATE_SOURCE_INGESTION`** flips to `false`, stopping ingestion.

The `oauth-proxy` sidecar has 32 env vars live and 0 in the chart, and its args
differ by `--skip-auth-regex=^/mcp`. An apply removes the skip, so MCP clients
start receiving login redirects.

### Other Deployments

- **scheduler** — the chart puts the flags in `command`; live keeps
  `["python3", "-m", "cli.scheduler"]` and puts the same flags in `args`. Same
  behaviour, different pod template, so a restart. Three env vars are live-only:
  `STARGATE_CLUSTERS`, `STARGATE_ROUTE_PROBE`, `STARGATE_ROUTE_PROBE_TIMEOUT`.
- **postgres** — `PGDATA` is live-only. Adding it changes the template, so the
  database restarts for no reason.
- **babylon-worker** — `STARGATE_CLUSTERS` and
  `STARGATE_WORKSHOP_PROVISION_NAMESPACES` are live-only.
- **frontend** — the only difference is `imagePullPolicy`, which the chart omits
  and Kubernetes defaults to `IfNotPresent` while live says `Always`.
- Every Deployment's `imagePullPolicy` follows the same pattern.

### Objects that would fail or break

| Object | Problem |
|---|---|
| `PersistentVolumeClaim/stargate-postgres-pvc` | chart asks 40Gi, live is 80Gi. Shrinking a bound PVC is rejected, so the upgrade fails. |
| `ServiceAccount/stargate-frontend` | rendered **twice** in `templates/rbac.yaml`. The second copy sets an oauth redirect annotation pointing at Route `stargate-frontend`, which does not exist; live points at Route `stargate`. Applying risks a login redirect loop. |
| `Secret/stargate-secrets` | the chart renders three keys with empty values; live has eleven. Helm's three-way merge preserves the live values only because they differ from the stored empty strings. If anyone ever renders the chart with those values set, the live admin key and database password are overwritten. |

### Objects the chart does not manage at all

`stargate-demo` (Deployment, Service, Route, Secret), `stargate-beat` and
`stargate-worker` (both at 0 replicas), the `credential-replication` CronJob, the
`allow-from-*` and `allow-geolux-to-postgres` NetworkPolicies, and
`Role/RoleBinding stargate-scanner-portforward`. A Helm upgrade will not touch
these, which is fine, but it means the chart cannot be described as the source
of truth for the namespace even after reconciliation.

## Structural blocker

`api.env` in values is a literal map. There is no `extraEnv`, `extraEnvFrom`, or
any way to express `valueFrom.secretKeyRef`. Eleven of the live env vars are
secret references — the five migrated on 2026-11-25 plus the admin key, LiteLLM
key, GitHub token, Jira token, Postgres password and AAP token. Faithful
reconciliation therefore **requires a chart change**, not just a values change:
either a raw env list (`toYaml` of arbitrary entries, so `valueFrom` can be
expressed) or an `envFrom`-style secret map.

## Three postures

### (a) Make the chart faithful, then upgrade

Add `extraEnv`, split the scheduler's `command`/`args`, add the missing env
(`PGDATA`, `STARGATE_CLUSTERS`, probe vars, workshop vars), add
`--skip-auth-regex`, encode per-Deployment `imagePullPolicy`, fix the duplicate
ServiceAccount and its redirect annotation, set the PVC to 80Gi, and stop
managing `stargate-secrets`. Then gate on a clean diff and upgrade.

Honest cost: every one of the 28 live-only vars must be classified as
intentional or incidental, which means reading the deployment history and
asking about each. It also makes the chart a mirror of production rather than a
design, and the next person to add an env var inherits the same two-place edit.

Blast radius: a rolling restart of api, scheduler, babylon-worker and frontend,
plus a Postgres restart unless `PGDATA` is encoded exactly. No code changes —
the digests stay the same.

### (b) Take Helm out of production

Record that production is managed by `oc set` / `oc apply`, keep the chart for
fresh installs, and stop pretending the release object describes the namespace.
Cheapest and most truthful. The release secret stays as a failed relic, or is
deleted once the history is exported.

### (c) Fix the chart for installs only, never upgrade production

The same chart work as (a), with no upgrade attempted. New installs get a
correct chart; production keeps drifting. This is (a) without the rollout.

**Recommendation: (c).** The chart work in (a) is worth doing either way to make
fresh installs correct, and nothing in the current drift is degrading. Then, if
Helm ownership of production is wanted later, upgrade from a position where the
chart is already faithful and the diff gate is empty — a separate decision, made
on its own release day.

(a) should only be chosen deliberately, with the 28 vars adjudicated and a
quiet window, and never as a side effect of "let's get Helm consistent again".

## The gate, if (a) is chosen

A raw `helm template` versus live comparison never converges: the API server
defaults `protocol`, `weight`, `defaultMode`, probe thresholds and similar
fields, and Helm adds its own labels. Compare server-side instead:

1. Render with the real deploy-time values. Never retype the cookie secret —
   `--reuse-values` merges the stored release values (which hold
   `oauth.cookieSecret`) and then overlays `-f values-infra01.yaml`, so the
   digests win and the secret is carried forward unread.
2. `kubectl diff -f <(helm template …)` against the live namespace. This is a
   server-side dry run, so it shows the patch Kubernetes would actually compute.
   Success condition: the diff contains only intended changes — ideally none,
   which also means no unintended restarts.
3. `helm upgrade --dry-run=server`. This is where the PVC shrink and the Secret
   merge get rejected, before anything is written.
4. Capture `oc get all,secret,configmap -o yaml` first, and keep the previous
   ReplicaSets as rollback anchors.

Post-checks: only intended revisions bumped, `api` env count as expected,
`/health` `ok` **from inside the pod** (the route serves the oauth login page
for `/health`), `/mcp` returning 401 rather than a redirect, an oauth login
round-trip, and the Postgres pod age unchanged.

## Open decisions

- Which posture: (a), (b) or (c).
- If (a): the 28 live-only env vars need an owner decision each. Several are
  clearly intentional (`DRY_RUN`, `EXECUTION_TARGET`, the AAP/GeoLux endpoints);
  the six `STARGATE_GATE_*` flags in the chart are off everywhere, so it is not
  obvious they should be written into the Deployment at all.
- Whether `stargate-secrets` should be a chart object at all, or a documented
  prerequisite created before install.
- Whether the failed v7 release object should be deleted once its values are
  exported, so tooling stops treating it as a live release.
