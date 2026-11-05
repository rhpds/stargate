# StarGate Investigation Workflow

**The complete event flow from failure to verified remediation.**

## Overview

When a lab or workload fails on the RHDP platform, StarGate automatically dispatches an AI investigation agent to diagnose it. The agent has 15 read-only tools, runs up to 12 iterations, and produces a cited diagnosis with remediation guidance. Every diagnosis is auditable, every remediation is human-gated, and every claim is verified.

---

## 1. Trigger

Failures enter the investigation pipeline through two paths:

### Event-driven (real-time)

When any evaluation fails, the event bus emits `evaluation.failed`. The InvestigationConsumer checks:

- Is this lab anomalous? (failure rate above its baseline)
- Is this failure class recurring? (pattern matching against history)
- Rate limits: max per day, max per hour per catalog item, pattern-dedup window

If the attention classifier says yes, an InvestigationRecord is created and queued.

### Queue-driven (batch)

A background loop (every ~1 minute) scans for:

- Sandbox namespaces that are stuck or failed
- Source events in "new" state (unprocessed failure events from AAP or the scanner)

The loop claims batches of up to 50 related events per investigation.

---

## 2. Claim

Before the agent runs, the system claims the relevant source events:

- Events in "new" or "reopened" state are matched by lab_code + failure_class
- Claimed events get a 30-minute TTL — if the investigation dies, claims expire and events return to the queue for retry
- Links between investigations and their source events are persisted (investigation_source_events table)

---

## 3. Agent Execution

The investigation agent is a Claude Sonnet instance with an 11.6KB system prompt defining it as a senior OpenShift SRE. It runs an iterative tool-calling loop — up to 12 iterations, 480 seconds max.

### The 15 tools (all read-only)

| Category | Tools |
|---|---|
| **Cluster state** | `oc_read` (get/describe/logs on any reachable cluster) |
| **Workload identity** | `get_lab_identity`, `get_sandbox_placement` |
| **History** | `query_evaluations`, `query_lifecycle_outcomes`, `get_resolution_history` |
| **Control plane** | `get_provisioning_status`, `get_pool_status`, `list_reclamation_artifacts` |
| **Configuration** | `fetch_github_file` (read AgnosticV configs from GitHub) |
| **Intelligence** | `query_recent_changes` (GitHub PRs + Jira vs failure onset) |
| **Correlation** | `query_cluster_saturation` (capacity signature detection) |
| **Knowledge** | `search_knowledge` (RAG over 351 documented RCAs) |
| **Diagnostics** | `get_storage_diagnosis` (PVC/PV/storage state) |
| **Catalog** | `get_labagator_info` (catalog/schedule info) |

### Investigation strategy (system prompt)

The agent follows a 10-step strategy:

1. **Identify the lab** — what workload is this?
2. **Check pod status** — what's running, what's failing?
3. **Read crash logs** — what's the actual error?
4. **Read the AgnosticV config** — what was supposed to be deployed?
5. **Check resolution history** — is this a known pattern?
6. **Check pool status** — is capacity the issue?
7. **Check recent changes** — did a merged PR or resolved ticket cause this?
8. **Check cluster saturation** — are diverse symptoms pointing to one full cluster?
9. **Search documented knowledge** — does the team's RCA record already name this?
10. **Query hub clusters** — trace AnarchySubject/ResourceClaim lifecycle state on ocp-us-east-1 and ocp-us-west-2 (the Babylon control plane)

### Evidence sufficiency

Before accepting the diagnosis, the system verifies the agent called the right tools for the failure class. For example, a `pods_crashlooping` diagnosis requires both log reads AND the Git config fetch — a diagnosis without both is rejected.

### The report

The agent produces:

- **Root cause** (or "insufficient evidence" — honest uncertainty is acceptable)
- **Evidence** with citations to specific tool calls
- **Remediation suggestion** (from the taxonomy's guidance or the agent's analysis)
- **Confidence level**

If max iterations are reached without a report, a forced conclusion call (no tools) asks for best-effort analysis with available data.

---

## 4. Completion

- **Success**: source events → "diagnosed" state; investigation marked "complete"
- **Failure**: source events → "new" (returned to queue); investigation marked "error"
- The investigation record persists with root_cause, remediation, full evidence chain, tool call log, model used, iteration count, and execution time

---

## 5. Post-Investigation Paths

### Adjudication (blind review)

A separate LLM (granite) evaluates the diagnosis without seeing the agent's reasoning:

- **Confirmed**: high confidence, proceed to action
- **Needs human review**: uncertain, flagged for attention
- **Model supported**: reviewer reached the same conclusion independently

### Actionable → PendingAction

If the diagnosis maps to a remediation catalog entry:

- A PendingAction is created (human-review-only — never auto-executes)
- GeoLux performs a pre-approval constraint check (safe/unsafe/unknown)
- The action waits for human approval through the dashboard or MCP

### Human Review (via MCP)

Team members can review any diagnosis through the MCP `review_diagnosis` tool:

- **Approve** → the diagnosis is published to the versioned knowledge base
- **Reject** → the rejection is recorded with the reviewer's identity
- Future investigations cite confirmed knowledge entries in their evidence

### Verification

Subsequent evaluations of the same workload provide the ground truth:

- **Pass after fail** → a resolution_record is created (the problem resolved)
- **Continued failure** → the investigation stays linked for follow-up
- **MTTR** is computed from these fail→pass transitions

### Proof Lab (background)

Every ~6 hours, one proof cycle runs for the stalest failure class:

- Injects a synthetic instance of the failure
- Verifies the pipeline detects it with the correct classification
- Verifies the remediation resolves it
- **19 of 20 classes proven** (13 remediation-proof, 6 detection-proof)
- Gates decay on failure; `proven_ever` preserves history

---

## Key Metrics

| Metric | Value |
|---|---|
| Investigations completed | 2,066+ |
| Per day | 50–86 (rate-limited) |
| Root-cause rate | 91% |
| Cost per investigation | ~$0.20 (Sonnet) |
| Pending queue | 75,938 events (historical backlog from replays) |
| Claim TTL | 30 minutes |
| Max iterations | 12 (usage-optimized: 6) |
| Wall clock limit | 480 seconds |
| Clusters reachable | 8 provisioning + 2 hub (Babylon control plane) + infra01 + infra02 |

---

## Safety Model

- **All 15 tools are read-only** — the agent cannot modify anything
- **Remediation is human-gated** — 5 independent gates (namespace allowlist, execution mode, risk assessment, rate limiting, confidence threshold) + GeoLux governance + human approval
- **No auto-remediation on provisioning clusters** — verified via live RBAC probes
- **Every action is audit-logged** — who, what, when, with what evidence
- **Claims expire** — dead investigations release their events for retry

---

## Architecture

```
AAP job fails / Scanner detects failure
        │
        ▼
   source_event (new) ──▶ InvestigationConsumer
        │                       │
        │              attention_classifier
        │              (anomaly? rate limits?)
        │                       │
        ▼                       ▼
   Queue loop ──────────▶ InvestigationRecord (queued)
        │                       │
        │              claim_source_events
        │              (30-min TTL, linked)
        │                       │
        ▼                       ▼
   ┌─────────────────────────────────┐
   │   INVESTIGATION AGENT (Sonnet)  │
   │                                 │
   │   System prompt (11.6KB SRE)    │
   │   15 read-only tools            │
   │   Up to 12 iterations / 480s    │
   │                                 │
   │   Loop: LLM → tool → result     │
   │         → LLM → tool → result   │
   │         → ... → final report    │
   └─────────────┬───────────────────┘
                 │
                 ▼
   Diagnosis (root_cause + evidence + remediation)
                 │
        ┌────────┼────────┬──────────┐
        ▼        ▼        ▼          ▼
   Adjudication  Action   Human     Verification
   (granite     (Pending  Review    (fail→pass
   blind        Action,   (MCP      transition
   review)      GeoLux,   review_   = resolution)
                human     diagnosis
                gate)     tool)
```
