# Config Management for StarGate

**Problem:** every configuration change currently requires a full image build
and deploy (~10 min). Simple things — rotating a key, adding a cluster, tuning
an investigation limit — should not go through the build pipeline.

**Constraint (from Oct 30 2026):** Fridays are release day — a hard constraint
for commits and production deployments. Config changes need a lighter path.

## Current state

All `STARGATE_*` vars are set directly in the Deployment spec (via `oc set env`
over time). Changing one requires a pod rollout but NOT a rebuild — the build
is only needed for code. The gap: no separation of config from deployment, no
change history, no review surface.

## Level 1 — ConfigMap + Secret (immediate, no code change needed)

```
configmap/stargate-config        # non-secret: STARGATE_ADJUDICATION_*, limits, URLs, repos
secret/stargate-secrets          # credentials: DB URL, API keys, Jira/GitHub tokens
```

Deployment references both via `envFrom`:

```yaml
envFrom:
  - configMapRef: {name: stargate-config}
  - secretRef: {name: stargate-secrets}
```

- Config change = edit the ConfigMap + `oc rollout restart deploy/stargate-api`
  (~30s, no build)
- Credentials rotate in the Secret alone
- `oc set env` on the deployment is reserved for genuinely structural vars

## Level 2 — AAP as the change mechanism (the team's existing pattern)

The team already runs operational automation in AAP. A "StarGate config
change" job template gives:

1. **Controlled execution** — the playbook validates config before applying
   (schema check, required keys, no duplicate cluster names)
2. **Audit trail for free** — every config change is an AAP job with invoker,
   timestamp, and arguments
3. **The closed loop** — StarGate's AAP collector already ingests all four
   controllers. Config changes made via AAP appear in StarGate's own event
   stream, which means `query_recent_changes` (the change-correlation layer)
   sees them alongside PRs and Jira tickets. A config change that broke
   something is attributable the same way a merged PR is.

That last point is the reason to prefer AAP over raw ConfigMap edits: raw
edits are invisible to the change record; AAP jobs are not.

## What counts as a release

| Change type | Mechanism | Friday gate? |
|---|---|---|
| Code | commit → build → deploy | **Yes** |
| Config values | ConfigMap/Secret edit or AAP job + rollout restart | No — but log it (AAP job or Jira note) |
| Credentials | Secret rotation + rollout restart | No — rotations should not wait |
| Structural (new env var wiring) | `oc set env` + code awareness | Yes if code changes with it |

## Migration path

1. Extract current env from the deployment into ConfigMap + Secret
2. Switch the deployment to `envFrom`, verify parity (pod starts, all
   integrations healthy)
3. Create the AAP job template wrapping `oc patch configmap` + validation
4. Add STARGATE_GITHUB_TOKEN to the Secret when a fine-grained PAT exists
   (read-only, rhpds org scope)
