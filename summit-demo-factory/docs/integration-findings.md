# RHDP Validation Layer — Integration Findings

## The Problem

The Red Hat Demo Platform runs on multiple independent systems that each hold a piece of the operational picture but don't share it. Labagator knows the schedule. Demolition knows whether a lab runs. AgnosticV defines what should be deployed. Poolboy manages the resource pool. Anarchy tracks provisioning state. Cluster-scheduler scores infrastructure health. Each system stores its data independently. None of them feed into a shared context that could drive intelligent decisions.

When something fails, the LLM gets a terminal output and is asked to diagnose from scratch — no knowledge of what the environment should look like, how provisioning went, whether the cluster is healthy, or whether this same failure has happened before. The result is inconsistent analysis that can't distinguish a lab content bug from a platform issue from a capacity wall.

When a lab is marked "ready," nobody verified it against the spec. When ops gets a failure alert, they don't know if the session starts in 5 minutes or 5 days. When a remediation works, nobody records it. The same problems get re-diagnosed from zero every time.

## What Exists Today

**Labagator** — Lab deployment scheduler. Tracks 55 Summit labs across 8+ clusters. Manages the planning pipeline (intake → development → code freeze → ready), capacity planning, cost estimation, scheduling, and ops handoff. Reads CatalogItem CRDs from Babylon for catalog metadata. Has an AI chatbot (Claude via Vertex AI) for querying event data. Does not validate environments. Does not communicate with Demolition despite Demolition having built an integration API for it.

**Demolition** — Lab execution engine. Drives showroom labs end-to-end via Playwright browser automation and terminal commands. Does preflight health checks (showroom URL, bastion SSH, instance state). Reads ResourceClaim CRDs from Babylon for environment info. Uses Claude for step failure analysis (critical/warning/expected classification) and load test error reports. Has Slack and email notifications, PostgreSQL persistence, and a coordinator web app. Preflight checks are hardcoded pass/fail with no failure classification or remediation mapping.

**AgnosticV** — The source of truth for what every lab environment should look like. Declares workloads (ordered list of Ansible collections to deploy), operator channels and versions, resource constraints (CPU, memory, instance counts), user provisioning specs, showroom configuration, timeouts, and component dependencies. This data is consumed by the provisioning pipeline but never by any validation or AI system.

**Poolboy** — Resource pool operator. Manages pre-provisioned ResourceHandles in pools, matches ResourceClaims to handles, tracks pool capacity and handle health. This data — how many handles are available, which are in error, which cluster each landed on — is visible only inside Kubernetes CRDs.

**Anarchy** — Provisioning lifecycle operator. Tracks every state transition of a provisioned environment via AnarchySubject CRDs — provisioning started, playbook running, provision complete, start failed, retries, destroying. Tower job status including duration and error messages. This data is visible only inside Kubernetes CRDs.

**Cluster-scheduler** — Infrastructure health scoring. Queries Prometheus for real-time CPU, memory, storage, VM count, node health, and alerts per cluster. Exposes scores via REST API. Consumed by Poolboy for placement decisions but not by any validation system.

## The Gap

No system assembles context from these sources into a unified evidence bundle. No system classifies failures against known patterns. No system tracks which remediations work. No system connects the schedule (when does this session start?) to the infrastructure state (is this environment healthy?). The LLM compensates for all of these missing connections by reasoning from raw terminal output — and produces inconsistent results because it doesn't have the information it needs.

## What the Validation Layer Does

A validation pipeline embedded inside Demolition that bridges these systems. Not a new application — a layer that connects what exists.

### Collect

Gather evidence from every system that knows something about an environment:

- **AgnosticV**: Declared workloads, operator channels, resource constraints, user counts, timeouts — the spec of what "correct" looks like
- **Anarchy**: AnarchySubject state — did provisioning succeed, how many retries, how long did it take
- **Poolboy**: Pool capacity — how many handles available, was this handle placed on a stressed cluster
- **Cluster-scheduler**: Infrastructure health — CPU/memory usage, active alerts, unhealthy nodes
- **Demolition preflight**: Runtime checks — showroom reachable, bastion SSH working, instance state correct
- **Labagator**: Operational context — session time, attendee count, room, ops assignments

Each of these is an evidence source. The collection layer queries them through their existing interfaces (Kubernetes API, REST endpoints, database) and normalizes into a common evidence format.

### Classify

Evaluate evidence against rubrics — declarative YAML files that define what "healthy" means for each stage of a lab environment. Rubrics specify entry criteria, exit criteria, failure classes, and recommended remediations.

Classification is deterministic. A missing namespace is always `namespace_missing`. Crashlooping pods are always `pods_crashlooping`. An operator on the wrong channel versus what AgnosticV declares is `operator_version_drift`. Pool exhaustion is `pool_capacity_exceeded`. These classifications are pattern matching against known conditions — no LLM needed, consistent every time, sub-second evaluation.

Rubrics can be auto-derived from AgnosticV specs. The declared workload list becomes a checklist of expected deployments. The operator channels become version constraints. The resource specs become capacity criteria. Instead of writing rubrics by hand for each lab, the system generates them from the spec that already exists.

### Bundle

Assemble classified evidence with historical context into an evidence bundle:

- Current evaluation result (pass/fail/warn with failure class)
- Historical evaluations of the same lab, stage, and cluster (last N runs with outcomes, failure classes, timestamps)
- What changed since the last passing run (git SHA diff, operator version changes, cluster load delta)
- Previous remediations attempted for this failure class and whether they resolved it
- Operational urgency from Labagator (session time, attendee count, time until session)

The bundle is persisted after every evaluation. Over time it builds a complete history per lab, per stage, per cluster — the institutional memory that no system has today.

### Reason

The LLM is called only for what the deterministic layer couldn't resolve — the unclassified failures, the ambiguous cases, the novel patterns. When it is called, it receives the full bundle:

Instead of: *"A pod crashed. Here's the output. What happened?"*

The prompt becomes: *"LB1088 on cnv-us-east-ocp-3. deployment-ready stage. 15 of 17 declared workloads healthy per AgnosticV spec. RHACS operator stuck on InstallPlanPending, expected channel rhacs-4.9 per AgnosticV. Cluster at 94% CPU per cluster-scheduler. Pool was at 90% capacity when this handle was claimed. Provisioning took 4 hours with 2 retries per Anarchy. This failure pattern has not been seen before on this cluster. Session starts in 45 minutes with 200 attendees. Here are the pod logs."*

The failure class constrains the domain. The history constrains the hypothesis space. The AgnosticV spec defines what should be there. The LLM reasons within boundaries instead of guessing in a vacuum.

### Act

Route the result back through existing channels:

- **Labagator**: Update ops status (ready / failed with classification). Priority based on session proximity and attendee count.
- **Slack**: Notification with failure class, urgency, and recommended remediation — not a generic alert but a specific, actionable message.
- **Rubric evolution**: If the LLM classified a novel failure, propose a new rubric rule (failure class + conditions + remediation). The proposal requires human review before it becomes a deterministic rule.

### Evaluate

Close the loop:

- After remediation, re-run validation. Did the environment pass? Record the outcome against the failure class and the remediation that was applied.
- Track remediation effectiveness over time. "Deleting the installplan resolved `operator_install_stuck` in 3 of 4 cases. Increasing memory limit resolved `pods_crashlooping` in 2 of 2 cases."
- Human feedback: when ops resolves an issue differently than the system recommended, capture what they actually did. This feeds the evidence bundle and corrects the remediation effectiveness data.
- Every failure the LLM analyzes today becomes a rubric rule tomorrow. The LLM's job shrinks over time. The deterministic layer grows. The system gets faster, cheaper, and more consistent with every failure it sees.

## How It Gets Built

The validation layer is not a new system. It is implemented inside Demolition, using Demolition's existing infrastructure:

- **Rubric engine** ported from StarGate (rubric loader, evaluator, failure classifier — pure Python, zero dependencies beyond Pydantic). Becomes a module in Demolition's coordinator backend.
- **Evidence collectors** extend Demolition's existing preflight. Instead of hardcoded `checkHttp()` returning pass/fail, collectors gather evidence into the shape the rubric evaluator expects.
- **Evidence persistence** uses Demolition's existing PostgreSQL database. New tables for evidence records (JSONB observed state, failure class, timestamp, cluster, lab code) and remediation tracking.
- **Notifications** use Demolition's existing Slack and email services with enriched payloads (failure class, urgency from Labagator, recommended remediation).
- **Labagator integration** uses Demolition's existing integration API (already built, currently unused). Add a callback endpoint in Labagator that Demolition POSTs to after validation. Add Demolition URL/API key to Labagator's config. Wire a "Validate" trigger in Labagator's ops UI.
- **Babylon/Poolboy/Anarchy data** collected via the Kubernetes API using existing kubeconfig infrastructure in Demolition.
- **AgnosticV specs** read via GitHub API (Demolition already does this for showroom repo discovery) or from CatalogItem CRDs on the Babylon cluster.

### Proving Ground

One lab. One cluster. One real AnarchySubject evaluated through the rubric engine against the AgnosticV spec. Confirm the failure classification is correct. Break something — scale a deployment to zero, kill a pod — and confirm the rubric correctly classifies it. Then wire the Labagator callback and confirm ops status updates. That's the proof. Everything else scales from a proven core.
