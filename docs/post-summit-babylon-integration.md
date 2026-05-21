# Post-Summit: Babylon/Poolboy/Anarchy/AgnosticV Integration Requirements

## Context

StarGate is currently read-only against all four systems. To move from monitoring to execution (Phase D), we need specific permissions and integration points with each layer.

---

## Current State (During Summit)

| System | What StarGate Does | Permission | Gap |
|---|---|---|---|
| **Babylon** | Reads AnarchySubject states | `cluster-reader` on ocp-us-east-1 | None — reads work |
| **Poolboy** | Reads ResourcePool capacity | `cluster-reader` on ocp-us-east-1 | **BLOCKED** — CRDs not included in cluster-reader |
| **Anarchy** | Reads provisioning state | Via Babylon worker | None — reads work |
| **AgnosticV** | Reads lab specs from YAML/GitHub | Local files + optional GitHub token | None — works offline |

---

## What We Need for Production Execution

### 1. POOLBOY — Read Access to Custom CRDs

**Who to ask:** Babylon/Poolboy operator admin on ocp-us-east-1

**What we need:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: stargate-poolboy-reader
rules:
  - apiGroups: ["poolboy.gpte.redhat.com"]
    resources: ["resourcepools", "resourceclaims", "resourcehandles"]
    verbs: ["get", "list", "watch"]
```

```bash
oc create clusterrolebinding stargate-poolboy-reader-binding \
  --clusterrole=stargate-poolboy-reader \
  --serviceaccount=default:stargate-scanner
```

**What this enables:**
- Dashboard shows actual pool capacity (currently 0)
- `pool_exhaustion` recommendations fire from real data
- Policy engine can detect when pools are running low
- Evidence pipeline includes real pool state in LLM context

**Risk:** Zero — read-only, identical to what the Poolboy dashboard itself reads

---

### 2. BABYLON/ANARCHY — Write Access for Provisioning Actions

**Who to ask:** Babylon operator admin on ocp-us-east-1

**What we need (Phase D only, after approval gate proven):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: stargate-executor-babylon
rules:
  # Delete stuck AnarchySubjects (cleanup_stuck action)
  - apiGroups: ["anarchy.gpte.redhat.com"]
    resources: ["anarchysubjects"]
    verbs: ["get", "list", "delete"]
    
  # Restart failed provisioning (retry action)
  - apiGroups: ["anarchy.gpte.redhat.com"]
    resources: ["anarchyruns"]
    verbs: ["get", "list", "delete"]
```

**What this enables:**
- `cleanup_stuck` recommendation can actually delete destroy-failed AnarchySubjects
- Stuck provisioning can be retried by deleting the failed AnarchyRun
- Frees pool capacity that's held by broken instances

**Risk:** Medium — deletes resources. Mitigated by:
- Confidence gate (only auto-execute above 0.8 threshold)
- Approval queue for lower confidence actions
- Rollback captures AnarchySubject state before deletion
- Dry-run mode available for verification first
- Only targets subjects in `destroy-failed` or `provision-failed` state

**Graduated rollout:**
1. Week 1: Read-only + dry-run logging (no actual deletes)
2. Week 2: Delete with approval gate (human approves each deletion)
3. Week 3: Auto-delete for `destroy-failed` subjects only (confidence > 0.9)
4. Week 4: Expand to `provision-failed` with lower threshold (0.8)

---

### 3. POOLBOY — Write Access for Pool Scaling

**Who to ask:** Poolboy operator admin on ocp-us-east-1

**What we need (Phase D, later stage):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: stargate-executor-poolboy
rules:
  # Scale pool min/max (pool_exhaustion action)
  - apiGroups: ["poolboy.gpte.redhat.com"]
    resources: ["resourcepools"]
    verbs: ["get", "list", "patch", "update"]
```

**What this enables:**
- `pool_exhaustion` recommendation can increase pool minimum
- Pre-emptive scaling before sessions start (based on Labagator schedule)
- Substrate routing can shift pool allocation between Gaudi/Xeon6 workloads

**Risk:** Medium-High — changes pool sizing. Mitigated by:
- Only modifies `spec.minAvailable`, not pool templates
- Approval gate required for all pool changes
- Before/after snapshot of pool state
- Maximum scale factor configurable (e.g., 2x current max)

**NOT needed initially.** Pool scaling is a later Phase D capability.

---

### 4. AGNOSTICV — Enhanced Constraint Loading

**Who to ask:** AgnosticV repo maintainer

**What we need:**
- `STARGATE_GITHUB_TOKEN` with read access to private AgnosticV repos
- OR: local clone of AgnosticV repos synced periodically

**What this enables:**
- Constraint classifier can compare lab specs against actual deployed state
- Detects: workload_not_deployed, operator_version_drift, resource_below_spec
- Evidence pipeline includes spec vs reality comparison in LLM context

**Risk:** Zero — read-only GitHub API access

**Current workaround:** Works without GitHub token using local YAML files. Less complete but functional.

---

### 5. COMPUTE CLUSTERS (ocpv05-09) — Write SAs

**Who to ask:** Cluster admin for each compute cluster

**What we need per cluster:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: stargate-executor-compute
rules:
  # Scale deployments (cluster_capacity action)
  - apiGroups: ["apps"]
    resources: ["deployments", "deployments/scale"]
    verbs: ["get", "list", "patch", "update"]
  
  # Restart pods (cleanup_stuck / smoke_test_failing)
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "delete"]
  
  # Rollout restart (smoke_test_failing)
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]
  
  # Read for verification
  - apiGroups: [""]
    resources: ["services", "endpoints", "namespaces", "events"]
    verbs: ["get", "list"]
  
  # Routes for showroom health verification
  - apiGroups: ["route.openshift.io"]
    resources: ["routes"]
    verbs: ["get", "list"]
```

**Create on each cluster:**
```bash
oc create serviceaccount stargate-executor -n default
oc create clusterrolebinding stargate-executor-binding \
  --clusterrole=stargate-executor-compute \
  --serviceaccount=default:stargate-executor
```

**Graduated rollout per cluster:**
1. Start with ocpv05 only
2. Dry-run for 1 week
3. Execution with approval gate for 1 week
4. Auto-execute (confidence > 0.9) for 1 week
5. Expand to next cluster

---

## Summary: What to Request

| Request | System | From Whom | Priority | Risk |
|---|---|---|---|---|
| Poolboy CRD read | ocp-us-east-1 | Babylon team | **High** (enables pool visibility) | Zero |
| GitHub token | AgnosticV repos | Repo maintainer | Medium | Zero |
| AnarchySubject delete | ocp-us-east-1 | Babylon team | Medium (Phase D) | Medium |
| Poolboy pool patch | ocp-us-east-1 | Poolboy admin | Low (later Phase D) | Medium-High |
| Compute cluster write SA | ocpv05 (then others) | Cluster admins | Medium (Phase D) | Medium |

### Order of Operations

```
1. Poolboy CRD read (zero risk, unlocks dashboard data)
   ↓
2. GitHub token for AgnosticV (zero risk, better constraints)
   ↓
3. Compute cluster write SA on ocpv05 (one cluster, Phase D start)
   ↓  dry-run → approval gate → auto-execute
4. AnarchySubject delete on ocp-us-east-1 (cleanup stuck instances)
   ↓  dry-run → approval gate → auto-execute
5. Remaining compute clusters (ocpv06-09)
   ↓
6. Poolboy pool scaling (last, highest impact)
```

Each step requires the previous step's gate to PASS before proceeding.

---

## Evidence Required for Each Request

When requesting access, provide:

1. **StarGate's safety record** — receipts from Phase A/B/C showing all gates passed
2. **Read-only track record** — N days of monitoring without incidents
3. **Rollback proof** — Phase C test showing capture → delete → restore works
4. **Confidence gate proof** — show that low-confidence actions queue for approval
5. **Audit trail** — show every action is logged with who/what/when/why
6. **Dry-run capability** — show actions can be tested without execution

All of this evidence is already generated and stored in the `receipts/` directory and Postgres.
