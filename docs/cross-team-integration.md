# Cross-Team Integration Asks for StarGate Data Connectivity

## Problem

StarGate aggregates data from 6 independent systems (Labagator, Babylon, Poolboy, Demolition, AgnosticV, Cluster Scanners). Each uses different identifiers for the same lab — there is no shared key. Current data connectivity averages ~36% across sources.

## Current State

| Source | Connectivity | Join Method | Reliability |
|--------|-------------|-------------|-------------|
| Labagator | 100% | Source of truth | High |
| AgnosticV | 61% | lab_code prefix match on directory name | Medium |
| Scanner | 36% | namespace suffix → CATALOG_TO_DEMO mapping | Medium |
| Pools | 31% | Cloud type → pool prefix | Medium |
| Babylon | 30% | summit_mapping lab_code extraction | Medium |
| LLM | 36% | Follows scanner (run_id composite key) | High |
| Demolition | ~55%* | lab_code substring in session name | Low |

*When Labagator API is responding correctly.

---

## Ask 1: Babylon/Anarchy — Label Namespaces with Lab Code

**Team**: Babylon / Anarchy (namespace provisioning)

**What**: When Babylon/Anarchy creates a sandbox namespace, add labels:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: sandbox-abc123-zt-ansiblebu
  labels:
    babylon.gpte.redhat.com/labCode: "LB1088"
    babylon.gpte.redhat.com/catalogItemName: "summit-2026.lb1088-code-red-breach-challenge-cnv"
    babylon.gpte.redhat.com/catalogBase: "zt-ansiblebu"
```

**Where**: AnarchyGovernor provisioning playbook — the step that creates the namespace.

**Why**: This is the **single highest-impact change**. StarGate's cluster scanner already collects namespace JSON (`oc get namespace -o json`). If the namespace carries `labCode`, the scanner can store it in EvaluationRecord directly. Every evaluation then traces back to a specific lab.

**Impact**:
- Scanner: 36% → **100%**
- LLM: 36% → **100%**
- Full pipeline traceability: Lab → Namespace → Evaluation → Classification

**Effort**: Low — 2-3 lines in the provisioning playbook. Add labels to the namespace creation task.

**Example Ansible**:
```yaml
- name: Create sandbox namespace
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: "{{ sandbox_namespace }}"
        labels:
          babylon.gpte.redhat.com/labCode: "{{ lab_code }}"
          babylon.gpte.redhat.com/catalogItemName: "{{ catalog_item_name }}"
```

---

## Ask 2: Demolition — Include Lab Code in Session Metadata

**Team**: Demolition (smoke testing)

**What**: When creating a smoke test session, include a `lab_code` field:

```json
{
  "name": "lb1088-code-red-breach-smoke-test",
  "lab_code": "LB1088",
  "catalog_item": "summit-2026.lb1088-code-red-breach-challenge-cnv",
  "worker_count": 60
}
```

**Where**: Session creation API — `POST /api/v1/integration/sessions`

**Why**: Currently StarGate matches sessions to labs by substring search (`"lb1088" in session_name`). This is fragile — can false-match similar lab codes (e.g., "lb10880"). A direct `lab_code` field eliminates ambiguity.

**Impact**:
- Demolition: ~55% → **100%**
- No more false positive/negative matching

**Effort**: Low — add an optional field to the session creation endpoint.

---

## Ask 3: Poolboy — Tag Pools with Lab Associations

**Team**: Poolboy (resource pool management)

**What**: Add labels/annotations to ResourcePool CRDs indicating which labs use them:

```yaml
apiVersion: poolboy.gpte.redhat.com/v1
kind: ResourcePool
metadata:
  name: zt-ansiblebu.ansible-network-automation.prod
  labels:
    poolboy.gpte.redhat.com/event: "summit-2026"
  annotations:
    poolboy.gpte.redhat.com/labCodes: "LB1347,LB1390,LB2655"
```

**Where**: ResourcePool CRD definitions — either in the pool YAML or via an operator that derives the mapping from CatalogItems.

**Why**: Pools are shared by catalog type, not per-lab. StarGate currently guesses which pool serves which lab based on cloud type. An explicit mapping enables accurate capacity planning per lab.

**Impact**:
- Pools: 31% → **80%+**
- Enables "Lab X needs 30 attendees but pool Y only has 5 available" recommendations

**Effort**: Medium — requires either manual annotation or automation to derive lab→pool associations from the Babylon catalog.

---

## Integration Timeline

```
Week 1: StarGate deploys canonical mapping table (no dependencies) ← DONE
Week 2: Send Ask 1 to Babylon team, create JIRA ticket
Week 3: Send Ask 2 to Demolition team, create JIRA ticket
Week 4: Babylon implements namespace labels
Week 5: StarGate scanner reads namespace labels, stores lab_code in evaluations
Week 6: Demolition implements lab_code field
Week 7: StarGate reads lab_code from session data, direct join
Week 8: Assess Pool ask, implement if feasible
```

## Expected Connectivity After Integration

| Source | Current | After Track 1 (mapping table) | After Track 2 (cross-team) |
|--------|---------|-------------------------------|---------------------------|
| Labagator | 100% | 100% | 100% |
| Babylon | 30% | 55% | 90%+ |
| Pools | 31% | 50% | 80%+ |
| Demolition | 55% | 55% | 100% |
| Scanner | 36% | 60% | 100% |
| AgnosticV | 61% | 70% | 75% |
| LLM | 36% | 60% | 100% |

## Contact

For questions about StarGate data connectivity:
- Platform: https://stargate.apps.cluster.example.com
- Architecture → Data Mapping tab shows live connectivity status
