# StarGate Proof Lab: From Detection to Proven Auto-Remediation

## 1. The Ecosystem

StarGate is a continuous operations platform for RHDP (Red Hat Demo Platform). It monitors ~8 OpenShift clusters running lab/demo environments. Three systems work together:

```
Deepfield (Signal Detection)
  Collects raw cluster state: pods, events, PVCs, quotas, routes
  Feeds evaluation events into the pipeline
      |
GeoLux (Hypothesis Engine)
  Receives failure signals from Deepfield/StarGate
  Generates hypotheses about root causes
  Classifies failures using MPC (Model Predictive Control) governance
  Learning store with 27+ learned patterns
  191K+ hypotheses generated
      |
StarGate (Operations + Remediation)
  Rubric-based readiness scoring (32 rubric files)
  Failure classification (84 pattern-based classes across 7 YAML sources)
  Sub-classification (17 sub-classes for granular root cause)
  AI investigation pipeline (configurable LLM via LiteLLM)
  Policy engine (deterministic recommendations)
  Remediation catalog (140 entries with risk levels)
  Action executor (5 independent gates)
  Proof Lab (synthetic testing of remediation)
```

### How a failure flows through the system

1. **Scanner** runs every 5/15/60 min per cluster tier. Collects pod state, events, PVCs from each sandbox namespace.

2. **Rubric evaluator** scores each namespace against readiness rubrics (deployment-ready, storage-clone-ready, vm-runtime-ready, etc.). A failed criterion produces a failure class.

3. **Failure classifier** matches event text against 81 regex patterns across 6 YAML files (k8s-events, AAP, alertmanager, infrastructure, summit, troshka). Sub-classifier refines into 30 sub-classes.

4. **Attention classifier** decides if the failure warrants investigation. Four levels: stuck (failing >2h), anomalous (unusual pattern), provisioning (mid-deploy), expected (known transient). Learned suppression skips classes with 3+ TRANSIENT verdicts unless the failure persists >4h with 0 passes.

5. **Investigation pipeline** runs AI-powered investigations. An LLM agent with 10 read-only tools (oc get/describe/logs, lab identity, GitHub file fetch, resolution history, pool status, storage diagnosis) iterates up to 10 times, minimum 5 tool calls. Produces:
   - Diagnosis (what's failing and why)
   - Root Cause (specific component)
   - Remediation Strategy (code link, watch-and-wait, or escalate)
   - Shadow Remediation (exact commands an operator would run)
   - Verdict: TRANSIENT / ACTIONABLE / UNKNOWN

6. **Resolution classifier** aggregates historical verdicts per failure_class + catalog_item. Labels each pair as `watch_and_wait`, `investigate`, or `candidate_for_auto_remediation` based on self-resolve rates and human intervention rates.

7. **Proof Lab** tests remediation in an isolated namespace (stargate-test). Injects real failures, detects them, runs the catalog remediation, and verifies whether it actually fixes the problem.

---

## 2. How We Proved It

### The investigation pipeline (built over prior sessions)

- Parallel investigation dispatch with ThreadPoolExecutor (no Redis/Celery)
- Attention classifier for intelligent triage
- Learned suppression with persistent-failure override (>4h, 0 passes)
- Lifecycle stage UI (queued -> dispatched -> running -> complete)
- Full-status dedup to prevent duplicate investigation records
- Human-readable skip reasons
- Deeper storage investigation with dedicated tool + min 5 tool calls

The pipeline processes 60-85+ investigations/day with a clean completion rate. Shadow Remediation output documents what an operator would do -- but was never tested until now.

### Discovery: the proof system already existed

When we explored synthetic testing, three parallel agents searched the codebase and found the infrastructure was already built:

- **21 failure injectors** (`engine/failure_injector.py`) -- create real broken K8s resources in `stargate-test`
- **Proof orchestrator** (`engine/proof_orchestrator.py`) -- full inject -> detect -> HITL gate -> remediate -> verify -> cleanup cycle
- **Proof tracker** (`engine/proof_tracker.py`) -- UNTESTED -> PROVEN gate progression (3 consecutive passes)
- **5 API endpoints** wired in `api/routers/admin.py`
- **Full ProofDashboard** React page at `/proof` with matrix, timeline, AI explanations, HITL buttons
- **Action executor** (`api/action_executor.py`) -- 5-gate pipeline with mock/test/production modes

### What we built to activate it

**Phase 1 -- Make it operational:**
- `POST /admin/proof/run-batch` endpoint for batch runs (sequential, shared namespace)
- Scheduled proof sweep in the investigation loop (~every 6h, picks stalest class)
- "Proof Lab" nav link in the dashboard
- "Run All Untested" / "Run All" buttons in ProofDashboard
- `runProofBatch()` frontend API client method
- `stargate proof run/status/history` CLI commands

**Phase 2 -- Investigation-mode tracking:**
- 20 of 21 injectors create root-cause failures (e.g. `/bin/false` entrypoint) that catalog restarts can't fix. The tracker was treating these as FAILED -- misleading.
- Added `record_investigation_verified()` -- for investigation-type proofs, success = correct detection (not remediation fix). Gate progresses to `investigation_proven` after 3 passes.
- Fixed three race conditions in the orchestrator around Phase 1/Phase 2 result merging
- Fixed `_cleanup_scan_history()` deleting `proof-matrix.json` (matched `*.json` glob)

### Baseline results (Aug 21, 2026)

Ran all 20 failure classes in live test mode against `stargate-test` on infra01:

| Category | Count | Classes | Gate |
|----------|-------|---------|------|
| Remediation-verified | 12 | claim_misbound, datasource_unrecognized, deprecated_api, hpa_metric_failure, oom_killed, pvc_binding_failed, quota_exceeded, readiness_probe_failed, resolution_failed, sync_failed, volume_mount_failed, volume_resize_failed | low_risk_auto |
| Investigation-verified | 6 | backoff_limit_exceeded, image_pull_backoff, invalid_configuration, pod_pending, pods_crashlooping, scheduling_failed | manual |
| Detection timeout | 2 | image_pull_secret_missing, volume_attach_failed | manual |

- **12 remediation-verified**: catalog fix actually works in the test namespace. Auto-promoted to `low_risk_auto` gate.
- **6 investigation-verified**: detection is correct, but the failure requires root-cause understanding (not a generic restart). The proof system honestly reports this -- proving the detection pipeline works, not that a restart fixes everything.
- **2 detection timeout**: detection patterns need tuning for these edge cases.

---

## 3. How It Will Work: The Auto-Remediation Roadmap

### Gate progression

```
UNTESTED --> INJECTED --> DETECTED --> REMEDIATED --> VERIFIED --> PROVEN
                                                        |            |
                                                   1 pass       3 passes
                                                 low_risk_auto  full_auto

Investigation mode (detection correct, remediation insufficient):
DETECTED --> VERIFIED --> PROVEN (investigation_proven)
               |             |
          1 pass        3 passes
```

### What PROVEN unlocks

PROVEN means the proof system ran 3 consecutive successful cycles -- the remediation mechanism is reliable. But PROVEN alone doesn't enable auto-remediation. The action executor has 5 independent gates that ALL must pass:

```
Gate 0: Namespace Allowlist
  Only sandbox-*, launchpad-*, stargate, deepfield, intel-rh-*, user-demo-*, partner-ai-*
  stargate-test always passes

Gate 1: Lab Execution Mode (per-lab config via LabRemediationConfig)
  recommend_only (DEFAULT) -- log only, never execute
  low_risk_auto -- execute low-risk catalog actions automatically
  full_auto -- execute any catalog action automatically

Gate 2: Dry-Run
  STARGATE_DRY_RUN=true --> log everything, execute nothing

Gate 3: Confidence Threshold
  Below 0.8 --> queued for human approval (PendingAction)
  Slack notification sent to operators

Gate 4: Execution Mode
  mock (default) -- in-memory simulation via MockCluster
  test -- real oc commands with state snapshot + rollback on failure
  production -- currently disabled ("requires Phase D write SA")
```

### Step 1: Reach PROVEN (now -> 2-3 days)

The 12 remediation-verified classes need 2 more successful cycles each.
- **Organic**: scheduled sweep runs 1 cycle every ~6h -> all 12 proven in ~3 days
- **Accelerated**: run 2 more batch cycles manually -> proven same day

### Step 2: Cross-reference with resolution classifier

The resolution classifier (`engine/resolution_classifier.py`) tracks which failure_class + catalog_item pairs are `candidate_for_auto_remediation` based on historical data. A class that is both PROVEN (mechanism works) and `candidate_for_auto_remediation` (pattern is consistent) is a strong candidate.

### Step 3: Pick one class for pilot

Best candidate: **readiness_probe_failed**
- Highest volume (~50% of all investigations)
- Mostly transient (self-resolves during provisioning)
- Proven remediation (rollout restart)
- Lowest blast radius (restarting a pod that's already failing)
- Most data points for confidence

Approach:
1. Set `LabRemediationConfig` for ONE specific sandbox lab to `low_risk_auto`
2. All other labs stay `recommend_only`
3. Monitor for 48h
4. Track success rate, blast radius, and false positives

### Step 4: Human-in-the-loop approval queue

For classes below the confidence threshold (0.8), actions go to the approval queue:
- `GET /admin/approval-queue` -- lists pending actions
- `POST /admin/approval-queue/{id}/approve` -- approves and executes
- `POST /admin/approval-queue/{id}/reject` -- rejects with reason
- Remediation page already shows these in the UI

This is the bridge: the system recommends, the human approves, the system executes.

### Step 5: Expand gradually

```
Week 1: readiness_probe_failed on 1 lab (low_risk_auto)
Week 2: Add quota_exceeded, pvc_binding_failed (low-risk, proven)
Week 3: Add remaining proven remediation classes
Week 4: Expand to more labs

Each expansion:
  1. Verify PROVEN status (3/3 cycles)
  2. Check resolution classifier recommendation
  3. Set per-lab config
  4. Monitor 48h before expanding
  5. Rollback if failure rate increases
```

### Step 6: Pull-based operator architecture (future)

From demo day feedback: instead of StarGate centrally pushing remediation commands via kubeconfigs, deploy per-cluster operators that:
- Pull approved remediations from StarGate's approval queue
- Execute locally with cluster-native RBAC
- Report results back
- Eliminate the central kubeconfig security concern

---

## 4. Safety Guarantees

Ten layers of protection, any one of which stops unauthorized execution:

1. **Proof Lab isolation**: only operates in `stargate-test` namespace (hardcoded `_validate_namespace()` raises ValueError for anything else)
2. **Action executor**: 5 independent gates, ALL must pass
3. **Per-lab config**: default is `recommend_only`, opt-in per lab
4. **Rollback**: test mode captures state snapshot before execution, auto-restores on failure
5. **Rate limiting**: max 5 actions per lab per hour
6. **Audit ledger**: tamper-proof hash-chained log of every action (proposed, executed, rolled back)
7. **Namespace allowlist**: only sandbox-* and known prefixes
8. **Read-only investigation**: all investigation tools use a read-only verb allowlist (get, describe, logs, adm)
9. **Human approval**: below-confidence actions queue for operator review
10. **Kill switch**: `STARGATE_DRY_RUN=true` stops all execution instantly
