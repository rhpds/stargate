# StarGate Platform Workflows

Step-by-step event flows through the platform — what happens, in what order,
and where the data lands. Anyone on the RHDP team should be able to trace
any workload's lifecycle from this doc.

For agent/MCP access, see [mcp-agent-guide.md](mcp-agent-guide.md).

---

## 1. The Main Loop: Detect → Classify → Investigate → Suggest → Approve → Verify

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    │
│  │ SCANNER  │───▶│ RUBRIC   │───▶│ CLASSIFIER   │───▶│ SONNET   │    │
│  │ (5m/15m/ │    │ EVALUATE │    │ (LLM + regex │    │ AGENT    │    │
│  │  1h)     │    │          │    │  + taxonomy) │    │ (15 tools)│    │
│  └────┬─────┘    └────┬─────┘    └──────┬───────┘    └────┬─────┘    │
│       │               │                 │                  │          │
│       ▼               ▼                 ▼                  ▼          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    │
│  │ Evidence │───▶│Evaluation│───▶│  Proposed    │───▶│Investiga-│    │
│  │ submitted│    │ Records  │    │Classification│    │tion +    │    │
│  │ to API   │    │(pass/fail)│   │(quality-gated)│   │diagnosis │    │
│  └──────────┘    └──────────┘    └──────────────┘    └────┬─────┘    │
│                                                            │          │
│                              ┌─────────────────────────────┘          │
│                              ▼                                        │
│                    ┌──────────────────┐                               │
│                    │ ACTIONABLE?      │                               │
│                    │ (verdict from    │                               │
│                    │  investigation)  │                               │
│                    └────┬────────┬────┘                               │
│                         │        │                                    │
│                    YES  │        │  NO (TRANSIENT/UNKNOWN)             │
│                         ▼        ▼                                    │
│              ┌────────────┐  ┌──────────┐                            │
│              │ Pending    │  │ Auto-    │                            │
│              │ Action     │  │ resolve  │                            │
│              │ (queued)   │  │ (shadow) │                            │
│              └─────┬──────┘  └──────────┘                            │
│                    │                                                  │
│                    ▼                                                  │
│              ┌────────────┐     ┌──────────┐                        │
│              │ GEOLUX     │────▶│ HUMAN    │                        │
│              │ precheck   │     │ decides  │                        │
│              │(safe/unsafe)│    │(approve/ │                        │
│              └────────────┘     │ reject)  │                        │
│                                 └────┬─────┘                        │
│                                      │ approve                      │
│                                      ▼                              │
│                              ┌──────────────┐                       │
│                              │ GATED        │                       │
│                              │ EXECUTOR     │                       │
│                              │ (5 gates)    │                       │
│                              └──────┬───────┘                       │
│                                     │                               │
│                                     ▼                               │
│                              ┌──────────────┐                       │
│                              │ VERIFICATION │                       │
│                              │ EVAL         │                       │
│                              │ (pass = done)│                       │
│                              └──────────────┘                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Step-by-step with data locations

| Step | What happens | Data lands in |
|------|-------------|---------------|
| 1. Scan | Scanner workers poll 8 clusters (cluster-05–09, infra01, infra02, us-east-1) on tiered schedules | `evidence` table via API |
| 2. Evaluate | Rubric evaluator checks evidence against stage criteria (tri-state: pass/fail/indeterminate) | `evaluations` table |
| 3. Classify | Unclassified failures go to the LLM (quality-gated) or regex taxonomy | `proposed_classifications` table |
| 4. Investigate | Attention classifier triggers Sonnet agent for anomalous namespaces | `investigations` table |
| 5. Diagnose | Agent collects evidence via 10 read-only tools, produces root_cause + remediation_suggestion | `investigations.root_cause`, `.remediation_suggestion` |
| 6. Adjudicate | Blind reviewers + judge evaluate the diagnosis (gated, runs when enabled) | `adjudications` table |
| 7. Queue | ACTIONABLE investigations queue a human-review action with catalog candidates + lineage | `pending_actions` table |
| 8. Precheck | GeoLux classifies the proposed action against constraints (safe/unsafe/unknown) | `pending_actions.parameters.geolux_check` |
| 9. Approve | Human reviews the action, the GeoLux check, and the evidence chain | `pending_actions.status` → approved |
| 10. Execute | Gated executor runs the remediation (5 independent gates, audit-logged) | `remediations` table |
| 11. Verify | Next passing eval for the workload is linked as proof of resolution | `remediations.verification_eval_id` |

---

## 2. Provisioning Lifecycle

```
PROVISION REQUESTED
       │
       ▼
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ WorkshopPro- │────▶│ AnarchySubject│────▶│ AAP Job      │
│ vision CRD   │     │ created       │     │ (provision)  │
│ (babylon)    │     │               │     │              │
└──────────────┘     └───────┬───────┘     └──────┬───────┘
                             │                     │
                             ▼                     ▼
                     ┌──────────────┐     ┌───────────────┐
                     │ towerJobs    │     │ Job status:   │
                     │ provision/   │     │ successful /  │
                     │ start        │     │ failed /      │
                     └──────┬───────┘     │ running       │
                            │             └──────┬────────┘
                            ▼                    │
                    ┌──────────────┐              │
                    │ EXPLICIT     │◀─────────────┘
                    │ OUTCOME      │
                    │ (contract)   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │SUCCEEDED │ │ FAILED   │ │ INDETER- │
        │          │ │          │ │ MINATE   │
        │state=    │ │condition │ │running/  │
        │started + │ │Fail=True │ │mixed     │
        │job=      │ │or job    │ │histories │
        │successful│ │=failed   │ │          │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │             │             │
             ▼             ▼             ▼
        Episode:      Episode:      Episode:
        gap-wp-       gap-wp-       (waits for
        success-*     failed-*       resolution)
        (pass)        (fail)
             │             │
             ▼             ▼
        Bus event:    Bus event:
        evaluation.   evaluation.
        passed        failed
```

**Key rule: termination ≠ success.** Only explicit job statuses
(`successful`/`failed`/`error`/`canceled`) count. A running pod or a deleted
namespace never proves success or failure.

---

## 3. Reclamation Lifecycle

```
DESTROY REQUESTED
       │
       ▼
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ AnarchySubject│────▶│ AAP Job      │────▶│ Namespace    │
│ desired_state │     │ (destroy)    │     │ deletion     │
│ = destroyed   │     │              │     │              │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                             │                     │
                             ▼                     ▼
                     ┌──────────────┐     ┌──────────────┐
                     │ towerJobs    │     │ Namespace    │
                     │ destroy/stop │     │ gone?        │
                     └──────┬───────┘     └──────┬───────┘
                            │                     │
                            ▼                     ▼
                    ┌──────────────┐     ┌──────────────┐
                    │ EXPLICIT     │     │ PVs released?│
                    │ OUTCOME      │     │ Subject gone?│
                    └──────┬───────┘     └──────┬───────┘
                           │                     │
              ┌────────────┼────────────┐       │
              ▼            ▼            ▼       ▼
        ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
        │RECLAIMED │ │ DESTROY  │ │ DESTROY │ │RESOURCE  │
        │          │ │ _FAILED  │ │ _STALLED│ │_LEAK     │
        │job=      │ │          │ │         │ │          │
        │successful│ │job=failed│ │destroying│ │subject   │
        │OR        │ │OR state= │ │≥ threshold│ │gone but │
        │all gone+ │ │destroy-  │ │          │ │PVs bound │
        │PVs freed │ │failed    │ │          │ │          │
        └────┬─────┘ └────┬─────┘ └────┬────┘ └────┬─────┘
             │             │             │           │
             ▼             ▼             ▼           ▼
        Episode:      Episode:      Episode:    Episode:
        gap-reclaim-* gap-teardown-* gap-teardown-* gap-pvleak-*
        (pass)        (fail)        (fail)      (fail)
```

**Key rule: disappearance ≠ reclaimed.** A deleted namespace alone proves
nothing — the destroy job must have explicitly succeeded, or all three
observations (subject gone + namespace gone + PVs released) must be present.

### What the investigation agent sees

When a reclamation fails, the Sonnet agent can call:

1. `query_lifecycle_outcomes(namespace)` — the outcome episodes
2. `list_reclamation_artifacts(namespace)` — what was left behind:
   namespace existence, leaked PVs (name, phase, size), sandbox placement,
   and concrete reclamation targets ("reclaim pv-abc", "final namespace cleanup")

---

## 4. AAP Event Collection (all 4 controllers)

```
┌─────────────────────────────────────────────────────┐
│                AAP CONTROLLERS                       │
│                                                     │
│  ┌───────┐  ┌───────┐  ┌────────┐  ┌────────┐     │
│  │ prod0 │  │ prod1 │  │ event0 │  │ event1 │     │
│  │(region-a)│  │(region-b)│  │(region-a) │  │(region-b) │     │
│  └───┬───┘  └───┬───┘  └───┬────┘  └───┬────┘     │
│      │          │          │           │           │
│      └──────────┴────┬─────┴───────────┘           │
│                     ▼                               │
│           ┌─────────────────┐                      │
│           │ AAP Collector   │                      │
│           │ (75s cycle)     │                      │
│           │                 │                      │
│           │ Queries:        │                      │
│           │ - failed jobs   │                      │
│           │ - successful    │                      │
│           │   jobs (24h)    │                      │
│           │ - job events    │                      │
│           │   (per failed)  │                      │
│           └────────┬────────┘                      │
│                     ▼                               │
│           ┌─────────────────┐                      │
│           │ source_events   │                      │
│           │ (idempotent,    │                      │
│           │  deduped by     │                      │
│           │  evidence hash) │                      │
│           └────────┬────────┘                      │
│                     ▼                               │
│           ┌─────────────────┐                      │
│           │ Gap Detection   │                      │
│           │ Layer           │                      │
│           │                 │                      │
│           │ provision jobs →│ provisioning        │
│           │ destroy jobs  → │ destroy-complete     │
│           │                │ episodes             │
│           └────────┬────────┘                      │
│                     ▼                               │
│           ┌─────────────────┐                      │
│           │ Event Bus       │                      │
│           │ evaluation.     │                      │
│           │ passed/failed   │                      │
│           │ (1 per episode) │                      │
│           └────────┬────────┘                      │
│                     ▼                               │
│           ┌─────────────────┐                      │
│           │ DeepField       │                      │
│           │ (lifecycle-     │                      │
│           │  typed signals) │                      │
│           └─────────────────┘                      │
└─────────────────────────────────────────────────────┘
```

---

## 5. Causal Chain (the smoking-gun artifact)

Query any investigation's full evidence chain:

```
GET /dashboard/causal-chain?investigation_id=N
  (or ?namespace=sandbox-xyz for the latest)
```

```
┌─────────────────────────────────────────────────────────┐
│ CAUSAL CHAIN                                             │
│                                                          │
│ T₀  Symptom eval (triggering_eval_id)                   │
│      └─ "pod restarted 14 times, CrashLoopBackOff"      │
│                                                          │
│     Evidence (agent tool calls)                          │
│      ├─ oc_read: get pods -n sandbox-xyz                 │
│      ├─ query_lifecycle_outcomes: 2 episodes             │
│      └─ get_storage_diagnosis: PVC bound, PV Released   │
│                                                          │
│     Diagnosis                                             │
│      ├─ root_cause: "database dependency unreachable"   │
│      ├─ remediation_suggestion: "restart deployment"    │
│      └─ verdict: ACTIONABLE (confidence 85)              │
│                                                          │
│     Adjudication (if blind review ran)                   │
│      └─ claims: observation=supported, root_cause=      │
│         supported [cited: eval-42, tool-3]              │
│                                                          │
│     Action (queued + approved)                           │
│      ├─ action_type: cleanup_stuck                       │
│      ├─ geolux_check: safe (2 constraints passed)        │
│      └─ catalog_recommendations: [cleanup_stuck]         │
│                                                          │
│ T₁  Remediation executed                                 │
│      └─ applied_at: 2026-10-29T18:04:51Z                │
│                                                          │
│ T₂  Verification eval (verification_eval_id)             │
│      └─ outcome: PASS — "healthy"                        │
│                                                          │
│ chain_complete: true                                     │
│ missing_legs: []                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 6. MCP Access (anyone with an agent)

```
┌────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Any Agent  │────▶│ StarGate MCP     │────▶│ Platform    │
│ (Cursor,   │     │ Server           │     │ Data        │
│ Claude,    │     │                  │     │             │
│ custom)    │     │ 8 query tools    │     │ - episodes  │
│            │     │ + ask (RAG)      │     │ - evals     │
│            │     │ + review_diagnosis│    │ - chains    │
│            │     │ + comment_action │     │ - taxonomy  │
└────────────┘     │                  │     │ - proofs    │
                   │ Auth: API key    │     │ - artifacts │
                   │ Rate: 60/min     │     │ - knowledge │
                   │ Audit: logged    │     │   base      │
                   └──────────────────┘     └─────────────┘
```

**12 tools total**: 9 read-only query tools, `ask` (natural-language RAG),
`get_cluster_saturation` (capacity correlation), `get_recent_changes`
(GitHub PRs + Jira change correlation), and 2 review tools (diagnosis
review + action comments). Review tools record opinions only — no
execution, no cluster access, no remediation.

The **investigation agent** (separate from MCP) has 15 tools including
`query_recent_changes`, `query_cluster_saturation`, and `search_knowledge`
(retrieval over the documented RCA record) — every finding layer is
agent-queryable.

See [stargate-mcp-agent-guide.md](stargate-mcp-agent-guide.md) for
connection configs and example questions.

---

## 7. Proof Lab Cycle (chaos harness)

```
INJECT ──▶ DETECT ──▶ GEOLUX ──▶ RECOMMEND ──▶ HITL ──▶ REMEDIATE ──▶ VERIFY ──▶ CLEANUP
 known     real      hypothesis   catalog       human    gated        namespace   proof
 failure   pipeline  + classify   mapping       gate     executor     clean?      resources
```

| Stage | Scored on | Green means |
|-------|-----------|-------------|
| inject | TDD | Failure successfully created |
| detect | TDD/EDD/CDD/BDD | Pipeline detected the right class |
| hypothesize | TDD/EDD/CDD/BDD | GeoLux generated hypotheses |
| classify | TDD/EDD/CDD/BDD | GeoLux classified correctly |
| recommend | TDD/EDD/CDD/BDD | Catalog action mapped |
| prove | TDD/EDD/CDD/BDD | Remediation verified clean |
| trust | TDD/EDD/CDD/BDD | Full chain proven |

**Gates:** `full_auto` = remediation proven (3+ consecutive clean cycles).
`investigation_proven` = detection proven only. Gates decay on failure;
`proven_ever` preserves history.

---

## Key Tables (where the data lives)

| Table | What it holds | Written by |
|-------|--------------|-----------|
| `evaluations` | Every pass/fail evaluation per stage per workload | Rubric evaluator |
| `proposed_classifications` | LLM classification proposals (quality-gated) | Auto-classifier |
| `investigations` | Sonnet agent investigations with tool calls + diagnosis | Investigation loop |
| `adjudications` | Blind review + judge verdicts on diagnoses | Adjudication loop |
| `pending_actions` | Queued remediation actions awaiting human approval | ACTIONABLE investigations, deepfield, proof |
| `remediations` | Executed remediations with verification links | Approved execution |
| `source_events` | Idempotent AAP job events (all 4 controllers) | AAP collector |
| `resolution_records` | Fail→pass transitions with resolution cause | Shadow mode |
| `knowledge_entries` | Reviewed + published diagnoses (versioned) | Human review |
| `event_log` | Every bus event (evaluation.passed/failed etc.) | Event bus |

---

## Guarantees (what the platform promises)

1. **Observed ≠ inferred** — every outcome is explicitly observed or marked
   INDETERMINATE. No guessing.
2. **Evidence lineage** — every investigation links to the eval that triggered
   it; every remediation links to the eval that verified it.
3. **Human authority** — GeoLux advises, the human decides, the gated executor
   acts. No auto-remediation on provisioning clusters, ever.
4. **Honest chains** — `missing_legs` tells you exactly what isn't proven.
5. **Read-only MCP** — agents can query everything, change nothing.
