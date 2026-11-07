# StarGate MCP Tool Cookbook

**One section per tool: what to ask, what it does, what you get back.**
Every example response below came from a real call against production
(Nov 6 2026). Copy the questions into your agent as-is — that's the
point.

This is the companion to `docs/stargate-mcp-agent-guide.md` (connection
setup, security model). This doc answers: *"I have a key — now what do
I actually ask?"*

---

## Which tool for which question

| If you're wondering... | Ask your agent to use |
|---|---|
| "What happened to lab X?" | `query_lifecycle_outcomes`, then `query_evaluations` |
| "Why did it fail?" | `get_causal_chain` (by namespace, or ask for the latest) |
| "Is anything on fire right now?" | `get_cluster_saturation`, `get_recent_episodes` |
| "Is this one bug or many? What's systematically broken?" | `get_known_issues` |
| "Did something change before it broke?" | `get_recent_changes` (with the lab code) |
| "What does this error mean?" | `ask`, or `get_failure_classes` for the full taxonomy |
| "Did it clean up after itself?" | `list_reclamation_artifacts` |
| "Can we trust the platform's fixes?" | `get_proof_matrix` |
| "This diagnosis is right / wrong" | `review_diagnosis` |
| "Context for whoever approves this action" | `comment_action` |
| Anything else, in plain English | `ask` |

**The workhorse pattern** for investigating one workload:

```
1. query_lifecycle_outcomes(namespace="sandbox-<guid>-<lab>")
2. query_evaluations(namespace=..., limit=10)          # the symptom history
3. get_causal_chain(namespace=...)                     # the investigation
4. review_diagnosis(investigation_id=..., approved=..) # your expertise
```

---

## Query tools

### 1. `ask` — plain-English questions, grounded answers

**What it does:** Retrieval-augmented answers from live platform data
and the knowledge corpus (taxonomy, workflows, Confluence RCA record).
Cites sources. Says when it doesn't know rather than guessing.

**Ask things like:**
- "Ask StarGate: did sandbox-abc123 get reclaimed and did anything leak?"
- "Ask StarGate what `teardown_stuck` means and how it's fixed"
- "Ask StarGate what the proof lab has proven so far"
- "Ask StarGate how the platform classifies failures"

**Arguments:**

| Arg | Type | Meaning |
|---|---|---|
| `question` | string (required) | Any question |

**Example call and real response:**

> **Q:** "What is the StarGate platform and what does it monitor?"
>
> **A:** *"StarGate is a lifecycle intelligence platform for the Red Hat
> Demo Platform (RHDP). It monitors lab environments across multiple
> OpenShift clusters, classifies failures using a qualified LLM and
> deterministic taxonomy, investigates anomalies with an AI agent
> (Sonnet with tool calls), and proves when remediation worked via
> verification evals. [source: doc:platform-overview]"*

**Good to know:** simple taxonomy lookups are instant (no LLM); complex
questions take ~2s (qwen3-14b synthesis); repeats are instant (5-min
cache). If the LLM is unreachable you still get the retrieved context,
just unsynthesized.

---

### 2. `query_lifecycle_outcomes` — what happened to a workload

**What it does:** Provision/reclamation episodes for one namespace's
lab: provisioning successes/failures, reclamation completions, failed
or stuck teardowns. A PASS destroy-complete means reclaimed; a FAIL
destroy is the finding, not staleness.

**Ask things like:**
- "Did sandbox-82cd9-zt-rhelbu provision successfully?"
- "Ask StarGate for the lifecycle outcomes of my lab over the last month"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `namespace` | string (required) | — | The workload namespace |
| `days` | int | 14 | Lookback window |

**Example call and real response:**

> `query_lifecycle_outcomes(namespace="ocpv-tenants", days=7)`
>
> *"No lifecycle outcome episodes found for ocpv-tenants in the last 7
> days. No provision/reclamation outcome is recorded; do not infer
> one."*

That's a negative answer with interpretation guidance — the tool tells
you the absence is a fact, not an inference. For a namespace that IS
tracked you'd see episodes like:

> *"destroy-complete | pass | reclaimed | AAP destroy job 312798 for
> ZT-RHEL-BU-LAB-DEVELOPER-CNV succeeded (reclamation-outcome/v1:
> reclaimed)"*

**Good to know:** use the full sandbox namespace
(`sandbox-<guid>-<lab-code>`), not the bare lab code. Non-sandbox
namespaces (infra tenants) have no episodes by design.

---

### 3. `query_evaluations` — the symptom history

**What it does:** Recent readiness evaluations for a workload: outcome
(pass/warn/fail/indeterminate), failure class, message, timestamp.
This is the raw pulse — what the platform observed, in order.

**Ask things like:**
- "Show me the last 10 evaluations for sandbox-82cd9-zt-rhelbu"
- "What's the evaluation history for my lab?"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `namespace` | string (required) | — | The workload namespace |
| `limit` | int | 10 | Number of evaluations |

**Example call and real response:**

> `query_evaluations(namespace="sandbox-82cd9-zt-rhelbu", limit=5)`
>
> ```
> 2026-11-06 14:09:35: fail — showroom_not_ready | Entry criterion not met: showroom_route_reachable
> 2026-11-06 14:09:30: warn — guest_agent_not_connected | Optional criteria failed: guest_agent_connected, guest_os_ready
> 2026-11-06 14:09:26: pass — none | All criteria passed
> 2026-11-06 14:09:25: indeterminate — none | Criteria unobserved: health_endpoint_returns_200
> 2026-11-06 14:09:22: pass — none | All criteria passed
> ```
>
> (Read bottom-up: two passing evals, one criterion unobserved, then
> the guest agent lost and the showroom route stopped answering — a
> workload dying in slow motion.)

**Good to know:** `indeterminate` means the criterion could not be
observed (scanner couldn't reach it) — distinct from `fail`. Warnings
are optional-criteria failures; the lab still works.

---

### 4. `get_causal_chain` — the full evidence chain

**What it does:** The complete chain for an investigation: symptom
eval → collected evidence (every tool call the agent made, with result
previews) → diagnosis → adjudication → action → remediation →
verification eval. `chain_complete` only when a verification eval
proved resolution; `missing_legs` reports what isn't proven yet.

**Ask things like:**
- "Show me the causal chain for sandbox-82cd9-zt-rhelbu"
- "Get the causal chain for investigation 2419"
- "Show me the latest investigation's evidence"

**Arguments:**

| Arg | Type | Meaning |
|---|---|---|
| `investigation_id` | int (optional) | Specific investigation |
| `namespace` | string (optional) | Latest investigation for this namespace |

Provide one of the two (both empty is an error).

**Example call and real response (trimmed):**

> `get_causal_chain(investigation_id=2419)`
>
> ```json
> {
>   "found": true,
>   "investigation": {
>     "id": 2419, "namespace": "sandbox-82cd9-zt-rhelbu",
>     "cluster": "ocpv06", "failure_class": "showroom_not_ready",
>     "status": "complete"
>   },
>   "symptom": {
>     "outcome": "fail", "failure_class": "showroom_not_ready",
>     "message": "Entry criterion not met: showroom_route_reachable"
>   },
>   "evidence": [
>     {"tool": "get_lab_identity", "result_preview": "No lab mapping found for guid 82cd9. Catalog item slug from namespace: zt-rhelbu"},
>     {"tool": "oc_read", "result_preview": "showroom-69c8d7c9b-56fmf  7/7  Running  0  9h ..."},
>     {"tool": "query_evaluations", "result_preview": "Last 15 evaluations for sa..."}
>   ],
>   ...
> }
> ```

Every diagnosis on the platform is backed by one of these — this is
the tool that makes the AI's reasoning auditable.

**Good to know:** the response is JSON (capped at 20k chars). The
`evidence` array is ordered as the agent collected it; the diagnosis
leg cites it. If `chain_complete` is false, read `missing_legs` before
trusting the outcome.

---

### 5. `get_recent_episodes` — the fleet's lifecycle pulse

**What it does:** Recent lifecycle episodes across all clusters
(gap-% runs): provisioning and reclamation outcomes with stage,
outcome, failure class, message. Optionally filter by stage.

**Ask things like:**
- "What lifecycle episodes happened in the last 24 hours?"
- "Show me recent destroy-complete episodes"
- "Any provisioning failures in the last day?"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `hours` | int | 24 | Lookback (1–168) |
| `stage` | string (optional) | — | Filter: `provisioning`, `destroy-complete`, `cluster-health` |

**Example call and real response (trimmed):**

> `get_recent_episodes(hours=24)`
>
> ```
> Recent lifecycle episodes (last 24h):
>   destroy-complete | pass | reclaimed | AAP destroy job 312798 for ZT-RHEL-BU-LAB-DEVELOPER-CNV succeeded (reclamation-outcome/v1: reclaimed)
>   destroy-complete | pass | reclaimed | AAP destroy job 331338 for RHPDS agd-v2.ocp-cluster-cnv-pools succeeded (reclamation-outcome/v1: reclaimed)
>   destroy-complete | pass | reclaimed | AAP destroy job 312794 for RHPDS agd-v2.ocp-cluster-cnv-pools succeeded (reclamation-outcome/v1: reclaimed)
>   ...
> ```
>
> (A healthy fleet reclaims continuously — this stream is mostly
> `pass | reclaimed`. Filter `stage="provisioning"` and look for
> `fail` rows to find trouble.)

**Good to know:** caps at 50 rows, newest first. Empty window returns
a clear "no episodes" message — that itself is a health signal.

---

### 6. `get_cluster_saturation` — is a cluster the problem?

**What it does:** Runs the capacity-saturation detector: which
clusters show the signature (failure-rate spike vs their own baseline
+ diverse symptom classes + labs failing here while passing
elsewhere). Returns severity, confidence, top classes, divergent labs,
and remediation guidance.

**Ask things like:**
- "Is any cluster saturated right now?"
- "Are the ocpv clusters healthy from a capacity standpoint?"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `window_hours` | int | 6 | Detection window (1–72) |

**Example call and real response:**

> `get_cluster_saturation(window_hours=6)`
>
> ```
> Cluster saturation report (window: last 6.0h, baseline: 7d, clusters analyzed: 13):
>   No clusters currently show the saturation signature.
>   Remediation for saturated clusters: check node memory and NotReady status;
>   if confirmed, disable the cluster in the catalog and let the queue drain.
>   Do not chase individual symptom failures — they share one cause.
> ```
>
> (This detector caught the Oct 13 ocpv08 memory exhaustion live. When
> it fires, the report names the cluster, the rate multiplier, the
> divergent labs, and the recommended move — disable the cluster, let
> the queue drain, fix the node.)

**Good to know:** this is the "one cause, many symptoms" detector.
If it names a cluster, don't triage individual lab failures on it —
they share the root cause.

---

### 7. `get_recent_changes` — what changed before it broke

**What it does:** GitHub PRs (agnosticv, agnosticd) and Jira tickets
(RHDPOPS, GPTEINFRA). With a `lab_code`, correlates changes against
that lab's failure onset: PRs touching its AgnosticV files and tickets
mentioning it, with "resolved-in-window" (the fix) annotated. RHDP has
no formal change management — this IS the change record.

**Ask things like:**
- "What changed recently that could explain failures?"
- "Correlate changes for lab ocp-cluster-cnv-pools"
- "Were there any PRs merged that touch my lab's files?"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `lab_code` | string (optional) | — | Correlate against this lab's failure onset |
| `lookback_hours` | int | 72 | PR lookback (Jira always ≥7d) |

**Example call and real response (trimmed):**

> `get_recent_changes(lookback_hours=48)`
>
> ```
> Recent changes (last 48h PRs, 7d tickets):
>   GitHub (0 merged PRs):
>   Jira (50 recently updated):
>     GPTEINFRA-18464 [Closed] Infra: ocpv04 ocpv-tenants stuck at 1 PG... OSD full
>     GPTEINFRA-18319 [New] Create architectural document proposing proxy for administrative
>     GPTEINFRA-18457 [In Progress] Troubleshoot ocpv07 worker issues
>     GPTEINFRA-18463 [New] Enforce minimum user threshold for White Glove Requests (40+ user
>     ...
> ```

**Good to know:** with `lab_code`, the report annotates each change's
`correlation` — `lab-path match`, `fleet-wide`, or `resolved-in-window`
(a change that landed after onset and looks like the fix).

---

### 8. `list_reclamation_artifacts` — what a dying workload left behind

**What it does:** Left-over artifacts for a tearing-down or reclaimed
workload: namespace existence, PVs still bound to it (leaked capacity),
sandbox placement state, reclamation episodes, and concrete reclamation
targets. Read-only `oc` queries against the workload cluster.

**Ask things like:**
- "Did sandbox-abc123 leak anything when it was reclaimed?"
- "What's left of user-jappleii-redhat-com's workload?"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `namespace` | string (required) | — | The workload namespace |
| `cluster` | string (optional) | "" | Cluster to query (auto-placed if empty) |

**Example call and real response:**

> `list_reclamation_artifacts(namespace="user-jappleii-redhat-com")`
>
> ```
> Reclamation artifacts for user-jappleii-redhat-com (cluster: default):
>   namespace: gone (or never on this cluster)
>   leaked PVs: none found
>   sandbox placement: Cannot extract guid from user-jappleii-redhat-com
>   lifecycle episodes: no episode summary
>   reclamation targets: none — workload appears fully reclaimed
> ```

**Good to know:** a clean response is the point — "no leaks" is a
positive finding. The interesting output is `leaked PVs: N` (stranded
capacity) or an existing namespace after a destroy-complete episode
(a stuck teardown).

---

### 9. `get_failure_classes` — the taxonomy, wire format

**What it does:** The complete failure-classification taxonomy: every
class with its detection patterns, severity, source catalog, and
category. This is the same data the classifier uses — 111 classes.

**Ask things like:**
- "Get the full failure taxonomy"
- "What failure classes exist for storage?"

**Arguments:** none.

**Example call and real response (structure):**

> `get_failure_classes()`
>
> ```json
> [
>   {"name": "teardown_stuck", "category": "reclamation",
>    "severity": "high", "source_catalog": "post-mortems",
>    "patterns": ["destroy job.*running for", "namespace.*terminating"]},
>   ...
> ]
> ```

**Good to know:** it's the full taxonomy as compact JSON — large. In
an agent session, ask targeted questions instead ("what does
`teardown_stuck` mean?") and let `ask` do the lookup. Use this tool
when you want the raw list, e.g. for building dashboards or filters.

---

### 10. `get_proof_matrix` — what the platform has proven

**What it does:** Proof-lab state per failure class: status, cycles,
consecutive passes, gate, last run — plus the summary by accumulated
proof. Gates: `full_auto` = remediation-proven (the platform proved a
fix works end-to-end); `investigation_proven` = detection-proven.

**Ask things like:**
- "What has the proof lab proven?"
- "Is pods_crashlooping remediation-proven or detection-proven?"

**Arguments:** none.

**Example call and real response (structure):**

> `get_proof_matrix()`
>
> ```json
> {
>   "classes": {
>     "pods_crashlooping": {
>       "status": "passing", "cycles": 9,
>       "consecutive_passes": 6,
>       "gate": "investigation_proven",
>       "last_run": "2026-11-06T04:00:00Z"
>     }, ...
>   },
>   "summary": {"total": 111, "proven": 41,
>     "proven_remediation": 12, "proven_detection": 29}
> }
> ```

**Good to know:** this is the trust surface — before relying on the
platform's remediation for a class, check its gate here. JSON, capped
at 30k chars.

---

### 11. `get_known_issues` — is this one bug or many?

**What it does:** Groups completed investigations that share one root
cause into fleet-level issues — so the platform says "this is ONE bug
affecting N workloads" instead of presenting N separate diagnoses
nobody acts on. Every issue lands in a bucket by who owns the fix:
**platform** (infra-side: router, node, cluster, capacity),
**platform_self** (StarGate's own evaluator/rubric is the diagnosed
fault), or **lab_family** (a shared chart/config bug spanning labs).
Per issue: signature, scope, root-cause and remediation excerpts, and
a representative investigation id for `get_causal_chain`.

**Ask things like:**
- "Is this one bug or many?"
- "What's systematically broken right now?"
- "Are any of these failures StarGate's own fault?"
- "What single fix would eliminate the most failures?"

**Arguments:**

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `window_hours` | int | 24 | Lookback (1–168) |
| `bucket` | string (optional) | "" | Filter to one bucket: `platform`, `platform_self`, `lab_family`, `unknown` (empty = all) |

**Example call and real response (trimmed):**

> `get_known_issues(window_hours=24)`
>
> ```
> Known issues (last 24h): 3 issues covering 22 investigations across 19 namespaces
>   Buckets: 1 platform, 1 platform_self, 1 lab_family
>
>   [platform_self] StarGate self-issue: showroom_not_ready across 4 namespaces
>     signature: showroom_not_ready|artifact:evaluator
>     4 investigations across 4 namespaces, first seen 2026-11-06T15:00Z, last seen 2026-11-06T19:00Z
>     root cause: the showroom_not_ready rubric was misapplied to a lab family that never deploys a showroom — ...
>     remediation: fix the evaluator's namespace-existence probe ...
>     representative investigation: #2422 (get_causal_chain(investigation_id=2422) for the full chain)
>
>   [lab_family] showroom_not_ready across 10 namespaces — zerotouch-1.10.2
>     signature: showroom_not_ready|artifact:zerotouch-1.10.2
>     10 investigations across 10 namespaces, first seen 2026-11-06T02:00Z, last seen 2026-11-06T18:00Z
>     root cause: zerotouch-1.10.2 Helm chart bug — nginx/proxy container port and SCC config ...
>     remediation: fix the chart's proxy container ports and the SCC ...
>     representative investigation: #2439 (get_causal_chain(investigation_id=2439) for the full chain)
>
>   [platform] showroom_not_ready on ocpv07: platform-side pattern
>     signature: showroom_not_ready|cluster:ocpv07
>     8 investigations across 5 namespaces on ocpv07, first seen 2026-11-06T06:00Z, last seen 2026-11-06T19:30Z
>     root cause: router-ingress-rhdp-net pod restarted 114 times (CrashLoopBackOff); ingress routing flaps ...
>     representative investigation: #2451 (get_causal_chain(investigation_id=2451) for the full chain)
>
>   Guidance: platform_self issues are StarGate bugs — file them in the stargate repo. platform issues are
>   infra-side — check the named component on the named cluster. lab_family issues are chart/config bugs —
>   one fix eliminates the whole class. Use get_causal_chain(investigation_id=...) for any issue's full
>   evidence chain.
> ```
>
> (All three buckets firing on the same symptom class in one window:
> the same `showroom_not_ready` surface trace has three different
> owners — a StarGate rubric bug, a Helm chart bug, and an unstable
> ingress router. Without this rollup that's 22 separate
> investigations; with it, it's three fixes.)

**Good to know:** detection groups only COMPLETE investigations with
an ACTIONABLE diagnosis — transient noise never becomes a known issue.
`platform_self` issues are StarGate's own bugs: file them in the
stargate repo. One `lab_family` fix often eliminates an entire failure
class. Follow up with `get_causal_chain` on the representative
investigation id for any issue's full evidence chain.

---

## Review tools (opinions only — nothing executes)

### 12. `review_diagnosis` — confirm or reject a diagnosis

**What it does:** Records your agreement or disagreement with an
investigation's diagnosis. **Approved** diagnoses with a root cause +
remediation suggestion are published to the versioned knowledge base
(attributed to you) so future investigations cite what you confirmed.
**Rejected** diagnoses are marked for re-examination and never used as
reference knowledge.

**Ask things like:**
- "Review investigation 2419 as approved — this matches what I've
  seen on ocpv07"
- "Reject that diagnosis, the root cause is wrong"

**Arguments:**

| Arg | Type | Meaning |
|---|---|---|
| `investigation_id` | int (required) | From `get_causal_chain`, `query_evaluations`, or `ask` |
| `approved` | bool (required) | `true` = agree, `false` = reject |
| `notes` | string (optional) | Your reasoning (kept with the review) |

**Example call and real response:**

> `review_diagnosis(investigation_id=2419, approved=true, notes="Matches what I've seen")`
>
> *"Review recorded for investigation 2419: APPROVED | Published to
> knowledge base as sandbox-82cd9-zt-rhelbu:showroom_not_ready v1.
> Future investigations for this failure class will reference this
> diagnosis."*

That's the flywheel: your expertise becomes prior knowledge for every
future investigation of that failure class.

**Good to know:**
- Requires a root cause + remediation suggestion to publish; otherwise
  the review is recorded but nothing is published (you'll be told)
- Idempotent: re-reviewing a published investigation returns "already
  reviewed and published... No changes made"
- What does NOT happen, ever: no remediation executes, no cluster is
  touched, no approval-queue item is approved

---

### 13. `comment_action` — context for the approver

**What it does:** Adds a comment to a pending remediation action,
visible to whoever reviews or approves it in the dashboard. Does NOT
approve, reject, or execute anything — it's context for the human
approver.

**Ask things like:**
- "Comment on action 42: the fix works but the pod needs recreating
  first, not just restarting"

**Arguments:**

| Arg | Type | Meaning |
|---|---|---|
| `action_id` | int (required) | From `get_causal_chain` or `ask` |
| `comment` | string (required) | Non-empty; capped at 500 chars |

**Example call and real response:**

> `comment_action(action_id=42, comment="I've seen this pattern before — the fix works but needs the pod recreated first.")`
>
> *"Comment added to action 42 (restart_workload → sandbox-abc123).
> The approver will see it when reviewing this action. This does NOT
> approve or execute anything."*

**Good to know:** if there are no pending actions you'll get "action
not found" — actions usually resolve quickly, so catch them while
they're pending (see them via `get_causal_chain`).

---

## Putting it together: three real sessions

### The morning health check (30 seconds)

```
you:  "Ask StarGate: is any cluster saturated right?"
      → get_cluster_saturation(6)      — no clusters saturated ✓
you:  "Any provisioning failures in the last 24 hours?"
      → get_recent_episodes(24, provisioning) — scan for fail rows
you:  "What changed recently?"
      → get_recent_changes(48)         — PRs + Jira for context
you:  "What's systematically broken right now?"
      → get_known_issues(24)           — one bug or many? whose fix?
```

### The "user says my lab is broken" triage (2 minutes)

```
you:  "Show lifecycle outcomes for sandbox-<guid>-<lab>"
      → query_lifecycle_outcomes       — did provision succeed?
you:  "Show the last 10 evaluations for it"
      → query_evaluations              — what failed, when did it start?
you:  "Correlate changes for that lab"
      → get_recent_changes(lab_code=…) — did a PR/ticket land before onset?
you:  "Show me the causal chain"
      → get_causal_chain               — the investigation's evidence
you:  "Approve that diagnosis — it matches what I saw"
      → review_diagnosis               — your expertise, captured
```

### The "did we clean up after the event" check

```
you:  "What reclamation episodes ran in the last 24 hours?"
      → get_recent_episodes(24, destroy-complete)
you:  "Did sandbox-<guid>-<lab> leak anything?"
      → list_reclamation_artifacts     — PVs, namespace, targets
```

---

## Response semantics you can rely on

- **Grounded, cited answers** — `ask` answers only from retrieved
  context and cites sources; when context doesn't answer the question,
  it says what's missing
- **Observed vs unobserved** — a PASS reclamation means an explicit
  destroy-job success or corroborated disappearance, never an
  inference; a FAILED destroy is a finding, not staleness
- **Provenance** — causal chains are complete only when a verification
  eval proved resolution; `missing_legs` reports exactly what isn't
  proven
- **Attribution** — reviews and comments are recorded with your hashed
  key ID; knowledge entries show who confirmed them

## Limits worth knowing

- Rate limit: 60 requests/minute per key
- `get_failure_classes` and `get_proof_matrix` return large JSON —
  prefer targeted `ask` questions in conversation
- Sessions are stateless — every call is independent; your agent holds
  the conversation
- `ask` synthesis uses the platform's metered LLM; if unreachable, you
  get retrieved context without synthesis
- All example responses above are from production, Nov 6 2026, and
  were verified live during the platform's first full tool walkthrough
