# StarGate — Centralized Validation Layer

## Context

Across the RHDP organization, multiple systems hold pieces of the operational picture — Labagator (scheduling/planning), Demolition (execution/testing), AgnosticV (environment specs), Poolboy (resource pools), Anarchy (provisioning lifecycle), cluster-scheduler (infrastructure health). None of them share data with each other or assemble a combined context for LLM consumption. Every AI-powered system reasons in isolation with partial data and no institutional memory.

StarGate becomes the centralized validation layer — a standalone system with its own database and event bus that collects evidence from all sources, classifies failures deterministically against rubrics, assembles evidence bundles with historical context, and provides structured input to LLMs when needed. It is a reusable resource that any system can plug into, not embedded inside another product.

The build follows red/green TDD with staged gates. Each stage earns trust before the next begins.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                          STARGATE                                │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │Collectors│→ │Evaluator │→ │ Bundler  │→ │  Nanoagent      │ │
│  │          │  │(Rubrics) │  │(History) │  │  Pipeline       │ │
│  └────┬─────┘  └──────────┘  └────┬─────┘  │                 │ │
│       │                           │         │ Filter→Correlate│ │
│       │                           │         │ →Triage→Impact  │ │
│       │                           │         │ →[LLM if needed]│ │
│       │                           │         └───────┬─────────┘ │
│  ┌────┴─────────────────────┐  ┌──┴──┐         ┌───┴─────────┐ │
│  │    Evidence Sources      │  │ DB  │         │  Consumers  │ │
│  │ • Babylon/Anarchy CRDs   │  │     │         │  • Slack    │ │
│  │ • Poolboy ResourceHandles│  │     │         │  • Labag    │ │
│  │ • cluster-scheduler API  │  │     │         │  • Demo     │ │
│  │ • AgnosticV specs (git)  │  │     │         │  • Any      │ │
│  │ • OpenShift resources    │  │     │         │             │ │
│  │ • HTTP probes            │  │     │         │  HITL       │ │
│  │ • Labagator (schedule)   │  │     │         │  Feedback   │ │
│  └──────────────────────────┘  └─────┘         └─────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**Own database** — PostgreSQL. Evidence records, evaluation results, failure classifications, remediation history, evidence bundles. Not inside Demolition's DB, not inside Labagator's DB. StarGate's data belongs to StarGate.

**Event bus** — Outbound events on state changes (evaluation completed, failure classified, remediation proposed). Consumers subscribe via webhooks or polling. Labagator gets ops status updates. Demolition gets validation triggers. Slack gets failure alerts. Any future system can register as a consumer.

**Pluggable collectors** — Each evidence source is a collector module with a standard interface. Adding a new data source = adding a new collector. No changes to the core engine.

**Reusable** — Not coupled to Demolition's runtime, Labagator's schema, or any specific lab format. Any system that can POST evidence or subscribe to events can use StarGate.

**Integrates into existing systems** — StarGate is not a replacement. It plugs into Demolition (as the validation engine behind preflight), Labagator (as the source of ops status truth), AgnosticV (as constraint definitions), and the Babylon stack (as evidence sources). Each integration is additive — existing systems gain capabilities without losing any.

| System | What StarGate adds to it |
|---|---|
| **Demolition** | Replaces hardcoded preflight pass/fail with rubric-based classification. Demolition calls StarGate's evaluate endpoint instead of its own checkHttp/checkSsh. Demolition's AI analyzer receives the evidence bundle instead of raw terminal output. |
| **Labagator** | Gets automatic ops status updates via StarGate events. Session urgency flows into StarGate for priority-aware alerting. Labagator's "Validate" button triggers StarGate instead of being a manual process. |
| **AgnosticV** | Workload specs become constraint definitions. StarGate reads common.yaml to know what "correct" looks like. No changes to AgnosticV itself — StarGate consumes it read-only. |
| **Babylon/Anarchy/Poolboy** | CRD state becomes evidence. StarGate reads AnarchySubject, ResourceClaim, ResourceHandle via the K8s API. No changes to these operators — StarGate is a read-only consumer. |
| **cluster-scheduler** | Health scores become gate criteria. StarGate calls the existing /evaluate endpoint. No changes to cluster-scheduler. |
| **Parsec** | StarGate becomes a tool in Parsec's agent loop — "how many gates failed today?" — via a simple REST query. |
| **Monitoring (Icinga/Grafana)** | StarGate emits Prometheus metrics (gate pass/fail rates, failure class distribution). Grafana dashboards visualize validation health. |

---

## Capabilities Beyond Core Evaluation

### Human-in-the-Loop (HITL)

The system proposes. Humans decide. Feedback flows back.

**Proposal review workflow**:
1. StarGate evaluates → produces AI proposal (rubric diff, remediation suggestion, failure summary)
2. Proposal stored with `status: proposed, requires_human_review: true`
3. Notification sent to reviewer (Slack or dashboard)
4. Reviewer acts:
   - **Approve** → proposal becomes a rubric rule (new failure class, new criterion, new remediation). Next time the pattern appears, it's classified deterministically.
   - **Reject with reason** → rejection reason stored. Pattern is flagged "reviewed, not actionable." LLM won't re-propose the same pattern.
   - **Modify and approve** → reviewer adjusts the conditions or remediation before it becomes a rule. The human's version is what ships.
5. Ops feedback on remediations: after ops resolves a failure, they record what they actually did via `POST /evaluations/{id}/feedback` with `action_taken`, `worked: true/false`, `notes`. This feeds remediation effectiveness tracking regardless of whether a proposal was involved.

**HITL surfaces**:
- Slack: proposal notification with approve/reject buttons (Slack interactive message)
- API: `GET /proposals?status=pending` → `PATCH /proposals/{id}` with `status: approved|rejected`
- Future: dashboard UI for batch review

### Evaluation of StarGate Itself

StarGate classifies failures. How do we know the classifications are correct?

**Classification accuracy tracking**:
- Every HITL feedback interaction is a labeled data point: StarGate said `pods_crashlooping`, ops confirmed (or corrected to `image_pull_failure`).
- Track: `correct_classifications / total_reviewed = accuracy rate` per failure class.
- Track: `unclassified_failures / total_failures = coverage rate`. As rubrics evolve, coverage should increase.
- Track: `false_positive_rate` — environments classified as failed that were actually healthy (ops overrides the classification).
- Track: `remediation_effectiveness` — per failure class, how often the recommended remediation resolved the issue on the next evaluation.

**Self-evaluation rubric** (StarGate evaluates itself with the same rubric engine):
- `classification_accuracy > 90%` → GREEN
- `classification_coverage > 80%` → GREEN (under 20% unclassified)
- `false_positive_rate < 5%` → GREEN
- `remediation_effectiveness > 60%` → GREEN
- Metrics exposed via `/metrics` endpoint and visualized in Grafana.

### Continuous Feedback Loop Closure

How proposals become rules. How rules decay.

**Promotion pipeline**:
1. LLM proposes new failure class from unclassified failure → `status: proposed`
2. Human reviews and approves → `status: approved`
3. Approved proposal written to rubric YAML as a new failure class (or new criterion, or new remediation entry)
4. Next occurrence of the same pattern → classified deterministically, no LLM needed
5. Track: how many times the new rule fires, whether it's accurate (from HITL feedback)

**Rule lifecycle**:
- **Active**: rule fires and produces correct classifications (confirmed by HITL feedback)
- **Under review**: rule fires but HITL feedback shows >30% disagreement — flagged for review
- **Stale**: rule hasn't fired in 90 days — not removed, but flagged as untested
- **Retired**: rule explicitly marked inactive after review (environment changed, rule no longer applicable)

**Remediation effectiveness loop**:
- Every time a remediation is applied (via HITL feedback), record: `failure_class + remediation_id + outcome (resolved/not_resolved)`
- Query: `GET /remediations/{id}/effectiveness` → returns success rate, sample size, last applied
- Remediations with <30% success rate after 5+ applications flagged for review
- Remediations with >80% success rate after 5+ applications promoted to "recommended" (bolded in alerts)

### Event Ingestion — Successes and Failures

Every evaluation emits an event — pass, fail, and warn. Not just failures.

**Why successes matter**:
- **Baseline**: you can't calculate "this lab passes 95% of the time" without recording the passes
- **Drift detection**: `environment.degraded` requires knowing it was previously passing
- **Recovery confirmation**: after remediation, the next PASS proves it worked
- **Accuracy measurement**: HITL feedback on correct classifications includes "yes, this PASS was correct"
- **Correlation**: "85 of 100 instances are passing" is as important as "15 are failing" — it tells you the failure is localized, not systemic
- **Cost justification**: total evaluations run, time saved, incidents prevented

**Event types** (all evaluations, not just failures):
- `evaluation.passed` — environment healthy, all stages pass
- `evaluation.warned` — passed with optional criteria failures
- `evaluation.failed` — required criteria failed, includes failure class
- `failure.unclassified` — failed but no rubric class matched (LLM candidate)
- `environment.degraded` — was passing, now failing (state transition)
- `environment.recovered` — was failing, now passing (state transition)
- `remediation.proposed` — AI proposal generated
- `remediation.applied` — human reported applying a fix
- `remediation.effective` — next evaluation passed after remediation

### Nanoagent Event Processing

Events are cheap to produce. The question is what processes them. Full LLM reasoning on every event is expensive and unnecessary. Instead: **deterministic nanoagents filter cheap, LLM reasons expensive**.

```
Event Stream
  │
  ├→ [Nanoagent: Filter]        ← deterministic, sub-millisecond
  │   Drops: routine passes, duplicate failures within window,
  │   known-flaky stages (configurable suppress list)
  │
  ├→ [Nanoagent: Correlate]     ← deterministic, SQL aggregation
  │   Groups failures by: lab+cluster, failure_class, time window
  │   Detects: >20% same class = systemic flag
  │   Detects: same class across multiple clusters = platform issue
  │   Detects: single cluster, multiple classes = cluster issue
  │
  ├→ [Nanoagent: Triage]        ← deterministic, priority math
  │   Calculates: priority = severity × impact / urgency
  │   Routes: critical+urgent → page. Low priority → digest.
  │   Deduplicates: same failure class on same lab within 15min = one alert
  │
  ├→ [Nanoagent: Impact]        ← deterministic, lookup + count
  │   Queries: Labagator for affected sessions and attendee counts
  │   Queries: Poolboy for remaining healthy pool handles
  │   Annotates event with: sessions_affected, attendees_affected,
  │   pool_remaining, estimated_blast_radius
  │
  └→ [LLM: Reason]             ← expensive, only when needed
      Triggered only by:
      - failure.unclassified (no rubric class matched)
      - Correlator flags systemic issue (needs root cause hypothesis)
      - Impact nanoagent shows blast radius > threshold
      Receives: full evidence bundle (current + history + constraints
      + correlation context + impact assessment)
```

**Nanoagent implementation**: each is a Python function registered as an event handler. Not microservices, not separate processes — functions in the event processing pipeline. They run synchronously in order. Only the final LLM step is async.

```python
# Example nanoagent interface
class Nanoagent:
    def should_process(self, event: Event) -> bool: ...
    def process(self, event: Event, context: EventContext) -> Event: ...
```

**Filter rules** (configurable YAML, not hardcoded):
```yaml
suppress:
  - type: evaluation.passed
    condition: routine  # no state change, not first pass after failure
  - type: evaluation.failed
    condition: duplicate_within_window
    window_minutes: 15
  - stage_id: smoke-test-ready
    failure_class: response_time_slow
    condition: known_flaky
```

**Cost model**:
- Filter nanoagent: ~0 cost (in-process boolean check)
- Correlate nanoagent: ~0 cost (SQL query against local DB)
- Triage nanoagent: ~0 cost (arithmetic on cached Labagator data)
- Impact nanoagent: ~0 cost (API call to Labagator, cached 60s)
- LLM reasoning: ~$0.01-0.05 per call (Claude Haiku for triage, Sonnet for root cause)
- Target: <5% of events reach the LLM. 95%+ handled deterministically.

### Continuous Re-validation (Drift Detection)

Environments degrade between validation and session start.

**Watch mode**: `stargate watch <namespace> --interval 15m --until <session-start-time>`
- Re-runs the same rubric evaluation at a fixed interval
- Compares result to previous evaluation
- State transitions (`PASS→FAIL`, `FAIL→PASS`) emit events that enter the nanoagent pipeline
- Routine passes (no state change) are filtered by the Filter nanoagent — no alert noise
- Stops at session start time (or on manual cancel)

**Implementation**: cron-based in Stage 4 (event bus). A registered "watch" creates a recurring evaluation trigger stored in the DB. The event bus fires it on schedule.

### Multi-Instance Correlation

At Summit, hundreds of instances of the same lab run simultaneously.

**Aggregation query**: `GET /labs/{lab_code}/status?cluster=<optional>`
- Returns: total instances, pass count, fail count, failure class distribution
- If >20% of instances fail with the same class → `systemic_failure` flag on the response
- Systemic failures get escalated alerts: "LB1688: 18 of 85 instances failing with `pods_crashlooping` on cnv-us-east-ocp-3 — systemic issue, not per-instance"

**Implementation**: SQL aggregation over the evidence/evaluation tables. No new data model needed — the data is already there if every instance's evaluation is persisted.

### Prioritization

Not all failures are equal. A lab failing 30 minutes before 200 attendees arrive is different from a lab failing on a cluster nobody is using until Thursday.

**Priority calculation**:
- `urgency = time_until_session` (from Labagator schedule)
- `impact = attendee_count` (from Labagator session)
- `severity = failure_class.severity` (from rubric: critical > warning > info)
- `priority = severity × impact / urgency`

**Priority affects**:
- Alert routing: critical+urgent → page on-call. Low priority → batch digest.
- Evaluation order: when multiple environments need validation, highest priority first.
- Event payload: priority score included in all events so consumers can filter.

### Additional Collectors (Staged)

Not in the initial build but designed for plug-in:
- **Network probe**: TCP connect + TLS handshake + DNS resolution to external dependencies
- **Credential validator**: check token expiry dates, API key validity against provider endpoints
- **GitOps sync**: ArgoCD Application sync state and health
- **Certificate checker**: TLS cert expiry on routes

Each follows the existing collector interface. Adding one = new module + new rubric criteria + new tests.

---

## Build Stages — Staged Gates with Red/Green TDD

### Internal Build Rubric

Each stage has entry criteria (what must be true to start), exit criteria (what must pass to ship), and a gate (who reviews and approves advancement).

```
Stage 0: Core Engine         → proves the evaluator works
Stage 1: Persistence         → proves evidence survives restarts
Stage 2: Live Collection     → proves it reads real infrastructure
Stage 3: Evidence Bundles    → proves historical context works
Stage 4: Event Bus           → proves consumers receive signals
Stage 5: Integration         → proves cross-system feedback loop
```

---

### Stage 0: Core Engine (port from existing StarGate)

**Goal**: Rubric evaluation works end-to-end with fixtures. Red/green TDD on the classification engine.

**Port from StarGate** (`/Users/jkershaw/Documents/StarGate/summit-demo-factory/`):
- `api/app/models.py` → Pydantic models (Run, Stage, Evidence, Rubric, StageOutcome)
- `api/app/rubric_loader.py` → YAML rubric parser
- `api/app/rubric_evaluator.py` → deterministic evaluator
- `api/app/schema_validator.py` → evidence schema validation
- `collectors/openshift/collect_resource_state.py` → all OpenShift collectors
- `collectors/openshift/evidence_normalizer.py` → stage normalizers
- `collectors/babylon/` → AnarchySubject collector
- `collectors/showroom/` → Showroom health collector
- `collectors/cluster_scheduler/` → Cluster health collector
- `api/app/ai/` → proposal models, failure summarizer, rubric proposer, runbook proposer, PR generator
- `rubrics/` → all rubric YAMLs
- `remediations/catalog.yaml` → remediation definitions
- `evidence-schemas/` → JSON schemas
- `fixtures/` → all test fixtures
- `tests/` → all tests

**New structure**:
```
stargate/
  engine/                    # Core evaluation engine (ported)
    models.py
    rubric_loader.py
    rubric_evaluator.py
    schema_validator.py
  collectors/                # Evidence collectors (ported + new)
    openshift/
    babylon/
    showroom/
    cluster_scheduler/
    labagator/               # NEW: schedule/urgency context
    poolboy/                 # NEW: pool state
  normalizers/               # Stage normalizers (ported)
  proposals/                 # AI proposal system (ported)
  rubrics/                   # Rubric YAML definitions (ported + new)
  remediations/              # Remediation catalog (ported)
  evidence_schemas/          # JSON schemas (ported)
  api/                       # NEW: FastAPI service
  db/                        # NEW: PostgreSQL persistence
  events/                    # NEW: Event bus
  tests/
  fixtures/
```

**TDD cycle**:
1. Write failing test: `test_rubric_evaluator.py::test_crashlooping_classified_correctly` — RED
2. Port evaluator code — GREEN
3. Write failing test: `test_anarchy_collector.py::test_healthy_anarchysubject` — RED
4. Port collector code — GREEN
5. Continue for each module

**Entry criteria**: None (this is stage 0)
**Exit criteria**:
- [ ] All ported tests pass (312+ tests)
- [ ] `make test` green
- [ ] `make validate-rubrics` green
- [ ] CLI can evaluate fixtures: `stargate evaluate fixtures/successful-container-run.yaml` → PASS
- [ ] CLI can evaluate fixtures: `stargate evaluate fixtures/failed-route-run.yaml` → FAIL with correct class

**Gate**: Self — automated test suite passing.

---

### Stage 1: Persistence & API

**Goal**: Evidence, evaluations, and failure classifications persist in PostgreSQL. API serves evaluations to any consumer.

**Build**:
- PostgreSQL schema: `runs`, `stages`, `evidence`, `evaluations`, `failure_classifications`
- FastAPI service with endpoints:
  - `POST /runs` — create a validation run
  - `POST /runs/{id}/evidence` — submit evidence
  - `POST /runs/{id}/evaluate` — evaluate against rubrics
  - `GET /runs/{id}/report` — full report with classifications
  - `GET /runs/{id}/bundle` — evidence bundle with history (stub — returns current only, history in Stage 3)
- Alembic migrations
- Containerfile (UBI9-based, matching existing pattern)
- podman-compose for local dev (PostgreSQL + API)

**TDD cycle**:
1. Write failing test: `test_db.py::test_evidence_persists_across_sessions` — RED
2. Build schema + repository — GREEN
3. Write failing test: `test_api.py::test_submit_evidence_returns_201` — RED
4. Build API endpoint — GREEN
5. Write failing test: `test_api.py::test_evaluate_returns_failure_class` — RED
6. Wire evaluator to API — GREEN

**Entry criteria**:
- [ ] Stage 0 exit criteria met

**Exit criteria**:
- [ ] Evidence submitted via API is retrievable after restart
- [ ] Evaluation results include failure class and are persisted
- [ ] API serves reports with stage outcomes, failure classes, and evidence counts
- [ ] All tests pass including DB integration tests
- [ ] Container builds and runs via podman-compose

**Gate**: Peer review — another developer runs `podman-compose up`, submits evidence via curl, gets correct evaluation.

---

### Stage 2: Live Collection

**Goal**: StarGate collects evidence from a real OpenShift cluster, evaluates it, and produces correct classifications. This is the wedge.

**Build**:
- Live collection script: `stargate collect <namespace> --kubeconfig <path>`
  - Runs `oc get` for pods, deployments, services, endpoints, routes, events, anarchysubject
  - Writes evidence JSON to the API
  - Triggers evaluation
- HTTP probe collector: hits showroom endpoints live
- cluster-scheduler collector: calls `/evaluate` API live

**TDD cycle**:
1. Write failing test: `test_live_collection.py::test_collect_from_fixture_dir_matches_api_submission` — RED (test that collecting from fixture JSON and submitting to API produces the same evaluation as direct fixture evaluation)
2. Build collection → API → evaluate pipeline — GREEN
3. Manual test against real cluster — observe result, add regression test for the specific lab

**The proof**:
- Pick one lab on one cluster
- Run `stargate collect` against it
- Confirm the evaluation matches reality:
  - Healthy environment → all stages PASS
  - Kill a pod → `pods_crashlooping` classification
  - Delete the route → `route_missing` classification
  - Scale deployment to 0 → `pods_not_ready` classification

**Entry criteria**:
- [ ] Stage 1 exit criteria met
- [ ] Access to at least one OCP cluster with a provisioned lab

**Exit criteria**:
- [ ] Live collection against a real environment produces correct PASS
- [ ] Deliberately broken environment produces correct failure class
- [ ] At least 3 different failure classes validated against real data
- [ ] Evidence from live collection is persisted in the database

**Gate**: Demo to stakeholder — run live collection, show the classification, break something, show the correct failure classification in real time.

---

### Stage 3: Evidence Bundles & Constraint Classification

**Goal**: Historical evidence accumulates. Bundles provide context for each evaluation. AgnosticV specs become constraints.

**Build**:
- **Evidence bundle query**: `GET /runs/{id}/bundle` returns:
  - Current evaluation result
  - Last N evaluations for same lab + stage + cluster
  - Failure class frequency for this lab
  - Previous remediations applied and their outcomes
  - Time since last passing run
  - What changed (git SHA diff if available)
- **AgnosticV constraint loader**: reads `common.yaml` for a lab (via GitHub API or local clone), extracts:
  - Declared workloads list
  - Operator channels and versions
  - Resource constraints (CPU, memory, instance counts)
  - User count and provisioning parameters
  - Timeout values
- **Constraint classification**: compare live evidence against AgnosticV spec:
  - Workload missing → `workload_not_deployed` with workload name
  - Operator wrong channel → `operator_version_drift` with expected vs actual
  - Resource under spec → `resource_below_spec` with delta
- **Rubric auto-generation**: derive rubric criteria from AgnosticV spec (optional exit criteria for each declared workload)

**TDD cycle**:
1. Write failing test: `test_bundle.py::test_bundle_includes_history` — RED
2. Build bundle query with historical lookups — GREEN
3. Write failing test: `test_constraints.py::test_missing_workload_classified` — RED
4. Build AgnosticV parser + constraint evaluator — GREEN
5. Write failing test: `test_constraints.py::test_operator_drift_detected` — RED
6. Build operator channel comparison — GREEN

**Entry criteria**:
- [ ] Stage 2 exit criteria met
- [ ] Multiple runs persisted (from Stage 2 live testing)

**Exit criteria**:
- [ ] Bundle endpoint returns current + historical evaluations
- [ ] Same failure class appearing 3+ times shows as a trend in the bundle
- [ ] AgnosticV workload spec parsed for at least 2 labs
- [ ] Constraint classifications fire correctly (workload missing, operator drift)
- [ ] Remediation outcome tracked (applied → next run pass/fail)
- [ ] All tests pass

**Gate**: Show bundle output to ops team member — they confirm the historical context and constraint classifications match their understanding of the environment.

---

### Stage 4: Event Bus & Consumers

**Goal**: State changes emit events. External systems receive them. Slack gets alerts with urgency.

**Build**:
- **Event types** (all evaluations, not just failures):
  - `evaluation.passed` — environment healthy, all stages pass
  - `evaluation.warned` — passed with optional criteria failures
  - `evaluation.failed` — required criteria failed, includes failure class
  - `failure.unclassified` — failed but no rubric class matched (LLM candidate)
  - `environment.degraded` — was passing, now failing (state transition)
  - `environment.recovered` — was failing, now passing (state transition)
  - `remediation.proposed` — AI proposal generated
  - `remediation.applied` — human reported applying a fix
  - `remediation.effective` — next evaluation passed after remediation
- **Consumer registration**: `POST /consumers` — register a webhook URL + event types
- **Webhook delivery**: POST events to registered consumers with retry (3 attempts, exponential backoff)
- **Built-in consumers**:
  - Slack: formatted blocks with failure class, lab code, urgency, recommended action
  - Labagator: POST to ops status endpoint (when built on Labagator side)
  - Demolition: trigger preflight on `evaluation.completed` with failures
- **Priority signal**: when Labagator context is available (session time, attendee count), include urgency in events: "LB1088, 200 attendees, session in 28 minutes"

**TDD cycle**:
1. Write failing test: `test_events.py::test_evaluation_emits_event` — RED
2. Build event emission after evaluation — GREEN
3. Write failing test: `test_events.py::test_webhook_delivered` — RED
4. Build webhook delivery with mock consumer — GREEN
5. Write failing test: `test_events.py::test_slack_format_includes_failure_class` — RED
6. Build Slack formatter — GREEN
7. Write failing test: `test_nanoagents.py::test_filter_suppresses_routine_pass` — RED
8. Build Filter nanoagent — GREEN
9. Write failing test: `test_nanoagents.py::test_filter_passes_state_transition` — RED
10. Verify Filter passes degraded/recovered events — GREEN
11. Write failing test: `test_nanoagents.py::test_correlator_detects_systemic_failure` — RED
12. Build Correlate nanoagent with SQL aggregation — GREEN
13. Write failing test: `test_nanoagents.py::test_triage_calculates_priority` — RED
14. Build Triage nanoagent with priority math — GREEN
15. Write failing test: `test_nanoagents.py::test_triage_deduplicates_within_window` — RED
16. Verify deduplication — GREEN
17. Write failing test: `test_nanoagents.py::test_impact_annotates_blast_radius` — RED
18. Build Impact nanoagent — GREEN
19. Write failing test: `test_nanoagents.py::test_only_unclassified_reaches_llm` — RED
20. Verify LLM is only called for unclassified + systemic + high-blast-radius — GREEN
21. Write failing test: `test_watch.py::test_degraded_environment_emits_event` — RED
22. Build watch mode (recurring evaluation + state transition detection) — GREEN
23. Write failing test: `test_watch.py::test_routine_pass_filtered_by_nanoagent` — RED
24. Verify watch passes go through filter, only state changes alert — GREEN

**Entry criteria**:
- [ ] Stage 3 exit criteria met

**Exit criteria**:
- [ ] Evaluation completion emits event
- [ ] Registered webhook receives event within 5 seconds
- [ ] Slack notification includes failure class, lab code, and recommended action
- [ ] Unclassified failures emit separate event type
- [ ] Event history queryable: `GET /events?lab=LB1088&type=failure.classified`
- [ ] Watch mode re-evaluates at interval and emits `environment.degraded` on state change
- [ ] Multi-instance aggregation detects systemic failure (>20% same class)
- [ ] Priority score included in event payload
- [ ] All tests pass

**Gate**: Wire Slack consumer, run live evaluation that fails, confirm Slack notification arrives with correct classification, priority, and remediation. Start a watch, break the environment, confirm `environment.degraded` event fires.

---

### Stage 5: Integration — The Closed Loop

**Goal**: Labagator → StarGate → Demolition → StarGate → Labagator. The full signals → decision → action → validate → learn cycle.

**Build — changes in StarGate**:
- **Labagator collector**: queries Labagator API for session schedule, attendee count, ops status. Adds urgency context to evidence bundles.
- **Poolboy collector**: reads ResourceClaim/ResourceHandle CRDs for pool state, handle health, placement info.
- **External evidence endpoint**: `POST /runs/{id}/external-evidence` — Demolition POSTs run results here.
- **Human feedback endpoint**: `POST /evaluations/{id}/feedback` — ops records what they actually did. Feeds remediation effectiveness tracking.
- **LLM integration**: for `failure.unclassified` events, assemble the full bundle (current evidence + history + AgnosticV constraints + Labagator urgency + Poolboy pool state + Anarchy provisioning history) and send to Claude for analysis. Structured response proposes new rubric class. Proposal requires human review.

**Build — changes in Labagator** (coordinated with Labagator team):
- Add `LABAGATOR_STARGATE_URL` config
- New endpoint: `POST /api/v1/ops/{lab_id}/validation` — receives StarGate evaluation results, updates ops status
- "Validate" button in ops UI calls StarGate instead of being manual
- Approaching session window triggers StarGate via webhook

**Build — changes in Demolition** (coordinated with Demolition team):
- Replace hardcoded preflight checks with StarGate evaluate calls: instead of `checkHttp()` returning pass/fail, submit evidence to StarGate and get back failure class + remediation
- Add StarGate callback: after preflight/run completes, POST results to `POST /runs/{id}/external-evidence`
- AI analyzer receives evidence bundle from StarGate instead of raw terminal output: `GET /runs/{id}/bundle` → include in Claude prompt

**TDD cycle**:
1. Write failing test: `test_integration.py::test_labagator_context_in_bundle` — RED
2. Build Labagator collector — GREEN
3. Write failing test: `test_integration.py::test_evaluation_triggers_labagator_update` — RED
4. Build Labagator webhook consumer — GREEN
5. Write failing test: `test_integration.py::test_unclassified_triggers_llm_with_full_bundle` — RED
6. Build LLM integration with bundle assembly — GREEN
7. Write failing test: `test_hitl.py::test_approve_proposal_creates_rubric_rule` — RED
8. Build proposal approval → rubric promotion pipeline — GREEN
9. Write failing test: `test_hitl.py::test_reject_proposal_prevents_reproposal` — RED
10. Build rejection tracking — GREEN
11. Write failing test: `test_hitl.py::test_human_feedback_updates_remediation_effectiveness` — RED
12. Build feedback endpoint + effectiveness tracking — GREEN
13. Write failing test: `test_hitl.py::test_ops_correction_overrides_classification` — RED
14. Build classification correction flow — GREEN
15. Write failing test: `test_loop.py::test_approved_rule_fires_deterministically` — RED
16. Verify promoted rule catches next occurrence without LLM — GREEN
17. Write failing test: `test_loop.py::test_stale_rule_flagged_after_90_days` — RED
18. Build rule lifecycle (active/under_review/stale/retired) — GREEN
19. Write failing test: `test_self_eval.py::test_accuracy_metric_updates_from_feedback` — RED
20. Build self-evaluation metrics (accuracy, coverage, false positive rate, remediation effectiveness) — GREEN

**Entry criteria**:
- [ ] Stage 4 exit criteria met
- [ ] Labagator ops status endpoint exists (coordinate with Labagator team)
- [ ] Demolition integration API accessible

**Exit criteria**:
- [ ] Labagator session approaching deploy window triggers StarGate validation
- [ ] StarGate evaluation result updates Labagator ops status
- [ ] Failed evaluation triggers Demolition preflight
- [ ] Demolition results flow back as StarGate evidence
- [ ] Unclassified failures produce LLM analysis with full bundle context
- [ ] LLM proposals include rubric diff with conditions and remediation
- [ ] Human feedback recorded and affects remediation effectiveness scores
- [ ] Full cycle demonstrated: schedule → validate → classify → notify → remediate → re-validate → learn

**Gate**: End-to-end demo with ops team. Lab approaching session time, StarGate validates, finds failure, classifies it, notifies Slack with urgency, ops applies remediation, StarGate re-validates, confirms fix, updates Labagator to ready.

---

## Build Matrix

Internal rubric for tracking build health across stages:

| Dimension | Stage 0 | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 |
|---|---|---|---|---|---|---|
| **Tests pass** | 312+ | +DB tests | +live tests | +bundle tests | +event tests | +integration tests |
| **Failure classes** | Fixture only | Persisted | Validated live | With constraints | With events | With LLM proposals |
| **Evidence sources** | Fixtures | API submitted | `oc get` live | + AgnosticV | + Labagator | + Poolboy/Anarchy |
| **History** | None | Single run | Multiple runs | Bundle query | Event log | Feedback loop |
| **Events ingested** | None | None | None | Pass + fail stored | All events streamed | Full pipeline |
| **Nanoagents** | None | None | None | None | Filter + Correlate + Triage + Impact | + LLM escalation |
| **HITL** | None | None | None | None | None | Approve/reject/feedback |
| **Drift detection** | None | None | None | None | Watch mode | Watch + alert |
| **Correlation** | None | None | None | None | Aggregation query | Systemic alerts |
| **Priority** | None | None | None | None | In event payload | Affects routing |
| **Self-evaluation** | Tests only | Tests + DB | + live accuracy | + coverage metrics | + effectiveness | Full metrics dashboard |
| **Consumers** | CLI | API | API + CLI | API + CLI | + Slack | + Labagator + Demolition |
| **LLM dependency** | None | None | None | None | None | Unclassified only |
| **Deploy** | Local | podman-compose | + real cluster | Same | Same | + cross-system |

**Key principle**: The LLM is not in the critical path until Stage 5, and even then only for unclassified failures. Stages 0-4 are fully deterministic. This means the system works, produces value, and earns trust before any AI dependency is introduced.

---

## Internal Build Rubric

StarGate validates environments with rubrics. We validate StarGate's own build with the same approach. Each dimension is evaluated at each stage gate review.

### Code Quality

| Criterion | Required | Measurement |
|---|---|---|
| All tests pass | Yes | `make test` exit code 0 |
| Test coverage > 80% | Yes | `make test-cov` → coverage report |
| No security vulnerabilities in dependencies | Yes | `pip audit` or equivalent |
| Linting clean | Yes | `ruff check` exit code 0 |
| Type checking clean | No | `mypy` (advisory, not blocking) |

### Functional Correctness

| Criterion | Required | Measurement |
|---|---|---|
| Fixture evaluations produce expected outcomes | Yes | `stargate evaluate fixtures/*.yaml` all match |
| Rubric YAML files valid | Yes | `make validate-rubrics` |
| Evidence schema contracts hold | Yes | `test_json_schema_contracts.py` |
| AI proposals enforce safety constraints | Yes | `test_ai_boundaries.py` — status=proposed, approved=false, requires_human_review=true |
| Deterministic gate isolated from AI | Yes | `test_ai_boundaries.py::TestDeterministicGateIsolation` |

### Operational Readiness (Stage 1+)

| Criterion | Required | Measurement |
|---|---|---|
| Container builds successfully | Yes | `make podman-build` exit code 0 |
| Service starts and serves health endpoint | Yes | `curl localhost:8080/health` → 200 |
| Database migrations run cleanly | Yes | `alembic upgrade head` exit code 0 |
| Evidence persists across restart | Yes | Submit → restart → query → data present |

### Live Validation (Stage 2+)

| Criterion | Required | Measurement |
|---|---|---|
| Live collection produces correct PASS for healthy env | Yes | Manual verification against real cluster |
| Live collection produces correct failure class for broken env | Yes | Break environment → verify classification |
| At least 3 failure classes validated against real data | Yes | Log of validated classes with cluster/lab |

### Evidence Quality (Stage 3+)

| Criterion | Required | Measurement |
|---|---|---|
| Bundle includes historical evaluations | Yes | 5+ runs → bundle query returns history |
| AgnosticV constraints parsed for ≥2 labs | Yes | Constraint violations detected correctly |
| Classification accuracy > 90% (from HITL feedback) | No | Tracked metric, advisory until sufficient sample size |
| Classification coverage > 80% | No | Tracked metric, advisory until sufficient sample size |

### Integration Health (Stage 5)

| Criterion | Required | Measurement |
|---|---|---|
| Labagator → StarGate trigger works | Yes | Session approaching → validation fires |
| StarGate → Labagator callback works | Yes | Evaluation → ops status updated |
| Demolition evidence flows to StarGate | Yes | Preflight result appears as evidence |
| HITL feedback recorded and affects metrics | Yes | Approve proposal → rubric updated |
| Full loop demonstrated end-to-end | Yes | Schedule → validate → classify → notify → fix → re-validate → learn |

---

## Verification — How to Know Each Stage Works

**Stage 0**: `make test` — all green. `stargate evaluate fixtures/*.yaml` — correct outcomes.

**Stage 1**: `podman-compose up` → submit evidence via curl → restart API → query evidence → still there. Evaluate via API → get failure class in response.

**Stage 2**: Point at real cluster → `stargate collect <namespace>` → PASS. Break something → re-collect → correct failure class. Three different failure classes validated.

**Stage 3**: Run 5 evaluations → query bundle → see history. Parse AgnosticV for a lab → see constraint violations. Apply remediation → next run passes → remediation marked effective.

**Stage 4**: Register Slack webhook → trigger failing evaluation → Slack message arrives with failure class and remediation. Query event history → events persisted.

**Stage 5**: Labagator shows session in 30 min → StarGate validates → fails → Slack alert with urgency → ops fixes → StarGate re-validates → passes → Labagator updated to ready. Full loop, one lab, one cluster, observed in real time.

---

## Repository

**New repo**: `rhpds/stargate` — separate from the prototype at `summit-demo-factory/`.

The prototype (`/Users/jkershaw/Documents/StarGate/summit-demo-factory/`) is a development sandbox. The new repo is the production system. Code is ported from the prototype, not symlinked or imported. Once the new repo is proven, the prototype has served its purpose.

**What ports from the prototype**:
- `engine/` — Pydantic models, rubric loader, rubric evaluator, schema validator
- `collectors/` — all OpenShift, Babylon, Showroom, and cluster-scheduler collectors
- `normalizers/` — all stage normalizers
- `proposals/` — AI proposal models, failure summarizer, rubric proposer, runbook proposer, PR generator
- `rubrics/` — all rubric YAML definitions
- `remediations/` — remediation catalog
- `evidence_schemas/` — JSON schemas
- `fixtures/` — all test fixtures
- `tests/` — all tests (312+)

**What's new in the production repo**:
- PostgreSQL schema with evidence history and remediation tracking
- FastAPI service with production endpoints (bundle query, event emission, external evidence, feedback)
- Event bus with webhook delivery and consumer registration
- AgnosticV constraint parser and rubric auto-generation
- Labagator and Poolboy collectors
- Human feedback endpoint
- LLM bundle assembly for unclassified failures
- Container deployment (Containerfile, podman-compose, OpenShift manifests)
- Ansible deployment playbook (matching Demolition/Labagator/Parsec pattern)
