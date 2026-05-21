# RHDP Integration Findings — StarGate Validation Layer

## The Problem

The Red Hat Demo Platform runs on multiple independent systems that each hold a piece of the operational picture but don't share it. Labagator knows the schedule. Demolition knows whether a lab runs. AgnosticV defines what should be deployed. Poolboy manages the resource pool. Anarchy tracks provisioning state. Cluster-scheduler scores infrastructure health.

Each system stores its data independently. None of them feed into a shared context. When something fails, the LLM gets a terminal output and is asked to diagnose from scratch — no knowledge of what the environment should look like, how provisioning went, whether the cluster is healthy, whether this same failure has happened before, or whether 200 attendees arrive in 30 minutes. The result is inconsistent analysis that can't distinguish a lab content bug from a platform issue from a capacity wall.

When a lab is marked "ready," nobody verified it against the spec. When ops gets a failure alert, they don't know the blast radius. When a remediation works, nobody records it. The same problems get re-diagnosed from zero every time.

## What Exists Today

### Systems and Their Data

**Labagator** — Lab deployment scheduler. Tracks 55 Summit labs across 8+ clusters. Manages the planning pipeline, capacity planning, cost estimation, scheduling, and ops handoff. Reads CatalogItem CRDs from Babylon for catalog metadata. Has an AI chatbot (Claude via Vertex AI) for querying event data. Does not validate environments. Does not communicate with Demolition despite Demolition having built an integration API for it.

**Demolition** — Lab execution engine. Drives showroom labs end-to-end via Playwright browser automation and terminal commands. Does preflight health checks (showroom URL, bastion SSH, instance state). Reads ResourceClaim CRDs from Babylon for environment info. Uses Claude for step failure analysis (critical/warning/expected classification) and load test error reports. Has Slack and email notifications, PostgreSQL persistence, and a coordinator web app. Preflight checks are hardcoded pass/fail with no failure classification or remediation mapping.

**AgnosticV** — The source of truth for what every lab environment should look like. Declares workloads (ordered list of Ansible collections to deploy), operator channels and versions, resource constraints (CPU, memory, instance counts), user provisioning specs, showroom configuration, timeouts, and component dependencies. This data is consumed by the provisioning pipeline but never by any validation or AI system.

**Poolboy** — Resource pool operator. Manages pre-provisioned ResourceHandles in pools, matches ResourceClaims to handles, tracks pool capacity and handle health. This data — how many handles are available, which are in error, which cluster each landed on — is visible only inside Kubernetes CRDs.

**Anarchy** — Provisioning lifecycle operator. Tracks every state transition of a provisioned environment via AnarchySubject CRDs — provisioning started, playbook running, provision complete, start failed, retries, destroying. Tower job status including duration and error messages. This data is visible only inside Kubernetes CRDs.

**Cluster-scheduler** — Infrastructure health scoring. Queries Prometheus for real-time CPU, memory, storage, VM count, node health, and alerts per cluster. Exposes scores via REST API. Consumed by Poolboy for placement decisions but not by any validation system.

### Verified Isolation

Systematically verified across all repos in the rhpds organization:

- **No system feeds Poolboy state to any LLM.** Labagator references Poolboy CRDs for resource discovery but never passes pool capacity or handle state to Claude.
- **No system feeds Anarchy state to any LLM.** No system reads AnarchySubject CRDs and includes provisioning lifecycle data in an LLM prompt.
- **No system feeds cluster-scheduler health to any LLM.** No system queries the cluster-scheduler API and passes health scores to an LLM.
- **No system feeds AgnosticV workload specs to any LLM.** Demolition reads AgnosticV for showroom repo URLs only. Nobody passes the declared workloads, operator channels, or resource constraints to an LLM.
- **No system feeds historical failure data to any LLM.** Demolition has a playbook cache (content-addressed lookup, not historical query). Chatbot-log-analyzer has ChromaDB RAG but stores only log chunks — no infrastructure context.
- **No system does rubric-based failure classification.** Demolition classifies failures as critical/warning/expected via the LLM. Neither system uses declarative rubrics or produces named failure classes with remediation mappings.
- **No system tracks remediation effectiveness.** No system records what fix was applied and whether the next run passed.
- **Labagator never calls Demolition's API.** The integration API in Demolition exists and is unused.
- **Demolition never calls back to Labagator.** Results go to Slack/email only. No ops status update.
- **No system prioritizes failures by session urgency.** No system combines Labagator's schedule data with failure severity.
- **No system does continuous re-validation of running environments.**

## The Gap

The centralized validation layer that bridges these systems does not exist anywhere in the organization. Specifically:

1. **No unified evidence collection** — nobody assembles state from Babylon + Poolboy + Anarchy + AgnosticV + cluster-scheduler + runtime probes into a single context
2. **No deterministic failure classification** — failures are either unclassified (pass/fail) or LLM-classified (inconsistent)
3. **No evidence bundles with history** — every diagnosis starts from scratch with no institutional memory
4. **No constraint classification from specs** — AgnosticV declares what should exist but nobody compares that to reality
5. **No event processing pipeline** — no system ingests success and failure events, filters noise, correlates patterns, triages by priority, and escalates only what needs reasoning
6. **No feedback loop** — no system tracks what remediations work, evolves classification rules from experience, or captures human corrections
7. **No cross-system integration for validation** — the systems that could inform each other don't talk

## What StarGate Does

StarGate is a standalone centralized validation platform with its own database and event bus. It collects evidence from all sources, classifies failures deterministically against rubrics, assembles evidence bundles with historical context, processes events through a nanoagent pipeline, and provides structured input to LLMs only when deterministic classification isn't sufficient.

### The Pipeline: Signals → Decision → Action → Validate → Learn

**Collect** — Gather evidence from every system that knows something about an environment:

- **AgnosticV**: Declared workloads, operator channels, resource constraints, user counts, timeouts — the spec of what "correct" looks like
- **Anarchy**: AnarchySubject state — did provisioning succeed, how many retries, how long did it take
- **Poolboy**: Pool capacity — how many handles available, was this handle placed on a stressed cluster
- **Cluster-scheduler**: Infrastructure health — CPU/memory usage, active alerts, unhealthy nodes
- **OpenShift**: Pod state, deployment health, route status, service endpoints, events
- **HTTP probes**: Showroom readyz/healthz, application smoke tests
- **Labagator**: Session time, attendee count, room, ops assignments — operational urgency

Each is a pluggable collector module with a standard interface. Adding a new data source = adding a new collector.

**Classify** — Evaluate evidence against rubrics deterministically. A missing namespace is always `namespace_missing`. Crashlooping pods are always `pods_crashlooping`. An operator on the wrong channel versus what AgnosticV declares is `operator_version_drift`. Pool exhaustion is `pool_capacity_exceeded`. Rubrics are YAML files that define entry criteria, exit criteria, failure classes (AND conditions), and recommended remediations.

Rubrics can be auto-derived from AgnosticV specs — the declared workload list becomes a checklist, operator channels become version constraints, resource specs become capacity criteria.

**Bundle** — Assemble classified evidence with historical context:

- Current evaluation result (pass/fail/warn with failure class)
- Historical evaluations of the same lab, stage, and cluster
- Failure class frequency and trend direction
- Previous remediations attempted and their outcomes (worked/didn't work)
- What changed since the last passing run (git SHA, operator version, cluster load)
- Operational urgency from Labagator (session time, attendee count, time until session)

The bundle persists after every evaluation. Over time it builds institutional memory per lab, per stage, per cluster.

**Process (Nanoagent Pipeline)** — Every evaluation emits an event — pass, fail, and warn. Events flow through four deterministic nanoagents before any LLM is called:

1. **Filter** — Drops routine passes (no state change), deduplicates failures within time window, suppresses known-flaky stages. Configurable YAML rules. Cost: zero.
2. **Correlate** — SQL aggregation detecting systemic patterns. >20% of instances failing with the same class = systemic. Same class across multiple clusters = platform issue. Single cluster with multiple classes = cluster issue. Cost: zero.
3. **Triage** — Priority calculation (severity × impact / urgency). Routes critical+urgent to page on-call, low priority to batch digest. Deduplicates same failure class on same lab within 15 minutes. Cost: zero.
4. **Impact** — Queries Labagator for affected sessions and attendee counts. Queries Poolboy for remaining pool handles. Annotates blast radius. Cost: one cached API call.

Target: <5% of events reach the LLM. 95%+ handled deterministically.

**Reason (LLM)** — Called only when nanoagents can't resolve:

- `failure.unclassified` — no rubric class matched
- Correlator flags systemic issue needing root cause hypothesis
- Impact nanoagent shows blast radius above threshold

The LLM receives the full evidence bundle — not raw terminal output. The failure class constrains the domain. The history constrains the hypothesis space. The AgnosticV spec defines what should be there. The LLM reasons within boundaries.

**Act** — Route results through existing channels:

- **Labagator**: Update ops status automatically (ready / failed with classification)
- **Slack**: Alert with failure class, priority, blast radius, and recommended remediation
- **Rubric evolution**: LLM proposes new failure class → human reviews → approved proposal becomes deterministic rule

**Validate** — After remediation, re-run validation:

- Did the environment pass? Record outcome against the failure class and the remediation.
- Track remediation effectiveness: "deleting the installplan resolved `operator_install_stuck` in 3 of 4 cases."
- Continuous watch mode re-evaluates at intervals between "ready" and session start, detecting drift.

**Learn (HITL Feedback Loop)** — Humans close the loop:

- **Approve/reject proposals**: LLM-proposed rubric rules require human review. Approved → becomes deterministic. Rejected with reason → pattern suppressed.
- **Ops correction**: ops records what they actually did vs. what was recommended. Corrects remediation effectiveness data and classification accuracy.
- **Rule lifecycle**: active rules that show >30% HITL disagreement → flagged for review. Rules that haven't fired in 90 days → stale. Explicitly retired when no longer applicable.
- **Self-evaluation**: StarGate tracks its own classification accuracy (correct/total from HITL feedback), coverage (classified/total), false positive rate, and remediation effectiveness. These metrics are the measure of whether the system is working.

Every failure the LLM analyzes becomes a rubric rule. The LLM's job shrinks over time. The deterministic layer grows. The system gets faster, cheaper, and more consistent with every failure it sees.

## How It Integrates Into Existing Systems

StarGate is a standalone system — its own repo (`rhpds/stargate`), its own database, its own API. It integrates into existing systems additively. No system loses capabilities.

| System | What StarGate adds | Integration mechanism |
|---|---|---|
| **Demolition** | Replaces hardcoded preflight pass/fail with rubric-based classification. AI analyzer receives evidence bundle instead of raw terminal output. | Demolition calls StarGate evaluate API. StarGate provides bundle for AI prompts. |
| **Labagator** | Automatic ops status updates. Session urgency in alerts. "Validate" button triggers StarGate. | StarGate events → Labagator webhook. Labagator schedule → StarGate collector. |
| **AgnosticV** | Workload specs become constraint definitions. No changes to AgnosticV. | StarGate reads common.yaml via GitHub API (read-only). |
| **Babylon/Anarchy/Poolboy** | CRD state becomes evidence. No changes to operators. | StarGate reads CRDs via K8s API (read-only). |
| **Cluster-scheduler** | Health scores become gate criteria. No changes to cluster-scheduler. | StarGate calls existing /evaluate endpoint. |
| **Parsec** | StarGate becomes a query tool — "how many gates failed today?" | Parsec adds StarGate tool to agent loop. |
| **Monitoring** | Gate pass/fail rates and failure class distribution in Grafana. | StarGate emits Prometheus metrics. |

## Proving Ground

One lab. One cluster. One real evaluation through the rubric engine against the AgnosticV spec. Confirm the classification is correct. Break something — scale a deployment to zero, delete a route, kill a pod. Confirm the rubric correctly classifies the failure with the right class and the right recommended remediation. That proves the core. Everything scales from there through staged gates, each earning trust before the next begins.
