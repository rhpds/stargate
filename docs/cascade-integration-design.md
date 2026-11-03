# Cascade Integration Design — Proposed

**Status: DRAFT / PROPOSED — decision deferred to week of Nov 9, 2026**
**Author: generated from the Nov 3 architecture review; requires review by Kershaw
before any implementation**

## Executive summary

The RHDP ecosystem currently runs **three parallel intelligence stacks collecting
overlapping signals**: DeepField (watch/inference/incidents), Cascade Compression
(signal compression/memory, deployed on infra01 since Aug 2026, 11 collectors
including one for StarGate itself), and StarGate (evaluation/investigation/knowledge,
which has absorbed most of the incident-intelligence function this quarter).

**Proposal: Cascade becomes StarGate's compression tier; StarGate remains the
intelligence and decision layer; DeepField's seat is sunset as a consequence,
not a decree.**

The integration is gated on the proof-vs-OSS pin reconciliation (see §6) and
should follow, not precede, team adoption of the current StarGate surface.

---

## 1. Current state (as audited and observed)

### 1.1 The signal-flow map

```
                         ┌─────────────────────────────────────┐
   AAP (4 controllers) ──┼──▶ StarGate: evaluations, 174k+     │
   Babylon, scanners,    │   source_events, investigations,    │
   LLM-health, deps,     │   causal chains, knowledge base     │
   storage/OLM monitors  └──────────────┬──────────────────────┘
                                          │ stage-level events only
                                          │ (thin direct HTTP; Kafka dead 4.5mo)
                                          ▼
                                   ┌─────────────┐
                                   │  DeepField  │ watch streams (300s),
                                   │             │ Splunk (120s), inferences
                                   │             │ (7-day retention), incidents
                                   └──────┬──────┘ (permanent; push-back only when
                                          │  severity=high AND RCA AND remediation)
                                          ▼
                                   StarGate: human-review-only PendingAction

   K8s, Prometheus, Poolboy, ──▶ Cascade (infra01, since Aug 2026):
   Babylon, GitOps, OVN,          11 collectors (incl. a StarGate collector),
   Labagator, AgnosticV,          nano dedup/suppress (~46%), trained CPU
   Stargate, AAP (live cursors)   heads (21–25ms), LLM rubric (remainder),
                                   memory (K8s 9,001 / AAP 1,611 / federated 1,217)
```

### 1.2 The problems

1. **Triple collection**: AAP is collected independently by StarGate, Cascade,
   and (via Splunk) DeepField. K8s signals: Cascade and DeepField both watch.
2. **DeepField's StarGate contract is the weakest link**: stage-level only, no
   reclamation signals, one-way incident push with restrictive conditions.
3. **StarGate's noise problem**: `showroom_not_ready` is 45% of all failures —
   signal or noise? No governed mechanism decides. Semantic dedup absent (the
   same failure across 100 namespaces = 100 evaluations).
4. **StarGate's unclassified backlog**: ~10k+ replayed failures await the LLM
   classifier — exactly the volume Cascade's deterministic tiers were built for.
5. **Cascade lacks a decision surface**: compression and memory without the
   incident/investigation lifecycle that turns survivors into action.

### 1.3 What each system uniquely holds

| | Cascade | StarGate | DeepField |
|---|---|---|---|
| Deterministic compression tiers | ✓ (governed, earned authority) | partial (regex patterns, no suppression lifecycle) | ✗ |
| Trained CPU classifiers | ✓ (21–25ms) | ✗ | ✗ |
| Governed suppression | ✓ (3 withdrawal paths, shadow 5%, GCL 1%) | ✗ | ✗ |
| Durable signal memory | ✓ (federated) | ✓ (evaluations, source_events) | partial (7-day inferences) |
| Investigation / RCA with citations | ✗ | ✓ (Sonnet agent, causal chains) | partial (RCA-gated incidents) |
| Remediation governance | ✗ | ✓ (5 gates, GeoLux, HITL) | ✗ (advisory only) |
| Validated incident methodology | ✗ | ✓ (incident-validation-2026-10) | ✗ |
| Real-time watch (300s) | ✗ (poll-based) | ✗ (tiered scans 5m+) | ✓ |
| Splunk integration | ✗ | ✗ | ✓ |

**Conclusion**: Cascade and StarGate are complements — Cascade is the front tier
of exactly the pipeline StarGate runs; StarGate is the decision surface Cascade
lacks. DeepField's remaining unique value (real-time watch, Splunk) is narrow
and absorbable.

---

## 2. Target architecture (reference)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            SIGNAL SOURCES                                │
│  AAP (4+1 controllers) · Babylon · Cluster scanners · K8s events ·        │
│  external deps · LLM gateways · storage/OLM · (Splunk via adapter, TBD)  │
└──────────────────────────────┬───────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STARGATE COLLECTION SPINE (single collection point — no triple polling)  │
│  idempotent source_events (proven: 500k+ jobs replayed, job-id dedupe,    │
│  historical timestamps preserved)                                         │
└──────────────────────────────┬───────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  CASCADE COMPRESSION TIER                                                │
│  POST /cascade (batch)                                                   │
│  ├── nano tier: dedup, qualified suppression, severity gate (~46%)        │
│  ├── value rules: deterministic thresholds                               │
│  ├── trained CPU heads: per-domain classifiers (21–25ms)                 │
│  └── survivors + head-classifications returned to StarGate               │
│  Governance: suppression authority earned by outcome feedback,           │
│  withdrawable (negative validation / GCL audit / shadow disagreement)    │
└──────────────────────────────┬───────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STARGATE INTELLIGENCE & DECISION LAYER                                  │
│  ├── taxonomy patterns (111 classes) reconcile with head classifications │
│  ├── LLM classifier: only the true remainder (quality-gated proposals)   │
│  ├── investigation agent (15 tools, cited evidence, causal chains)       │
│  ├── adjudication + knowledge base (compounding, human-reviewed)         │
│  ├── saturation / change / incident correlation                          │
│  └── remediation: 5 gates, GeoLux, human approval — never auto on        │
│     provisioning clusters                                                │
└──────────────────────────────┬───────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  OUTCOME FEEDBACK LOOP (the closed governance circuit)                    │
│  fail→pass transitions · resolution records · incident validation        │
│  verified outcomes ──▶ Cascade suppression-authority feedback:           │
│    "this pattern was noise (self-resolved)" earns suppression authority; │
│    "this pattern preceded real incidents" withdraws it                   │
└──────────────────────────────────────────────────────────────────────────┘

  DeepField: sunset path (§5) — dependents migrate; real-time watch and
  Splunk coverage absorbed or consciously dropped.
```

### 2.1 Why this shape

- **One collection spine** (StarGate's — it's the proven, idempotent, historical-
  timestamp-preserving path; the replay work just battle-tested it at 500k scale)
- **Compression before intelligence** (Cascade's tiers front the pipeline — the
  92%-duplicate observation from the platform pilot applies directly to StarGate's
  signal volume)
- **Decisions stay where the governance is** (StarGate's remediation gates,
  human approval, GeoLux — compression must never become the decision-maker,
  which is Cascade's own stated invariant)
- **Outcomes close the loop** (StarGate's validated outcomes are the ground truth
  Cascade's governed suppression needs — neither system has this alone)

---

## 3. Integration contract (draft)

### 3.1 StarGate → Cascade: batch compression bridge

```
POST {CASCADE_URL}/cascade
Authorization: from STARGATE_CASCADE_KEY (Secret)

{
  "signals": [
    {
      "id": "<source_event_id>",           # idempotency: StarGate event identity
      "type": "<failure_class or raw>",    # taxonomy class when known
      "severity": "high|medium|low",       # from taxonomy severity
      "source": "stargate/aap/prod0",      # controller/instance
      "grouping": "<catalog_item>",        # lab identity for semantic dedup
      "labels": {"cluster": "...", "guid": "..."},
      "evidence": {                        # bounded, sanitized
        "message": "<normalized_error>",
        "failing_task": "...", "role": "..."
      },
      "timestamp": "<occurred_at>"
    }
  ]
}
```

**Response handling**: survivors + head classifications map back onto
source_events (a `cascade_classification` field or sub-class); suppressed
signals receive a `suppressed_by` tag with the decision receipt — never
deleted, always auditable.

**Batching**: piggyback on the existing ingest flush (500-record batches);
add a bounded queue so cascade unavailability degrades to
passthrough-classification (StarGate's current behavior), never to data loss.

### 3.2 Cascade → StarGate: classifications and survivors

- Head classifications reconcile against the 111-class taxonomy (both systems
  already share the wire format lineage — DeepField pulls
  `GET /api/failure-classes` today; cascade's SC taxonomy JSON is the same shape)
- Disagreement (head says X, pattern says Y): the deterministic taxonomy wins
  initially; disagreements feed the qualification flywheel as new evaluation
  cases

### 3.3 StarGate → Cascade: outcome feedback (governance circuit)

```
POST {CASCADE_URL}/governance/outcome    (endpoint to design with cascade side)

{
  "signal_group": "<suppression group id or pattern identity>",
  "outcome": "self_resolved | incident_confirmed | remediated | noise_confirmed",
  "evidence": "<resolution_record / incident link>",
  "window": "..."
}
```

- `self_resolved` + recurring → earns suppression authority
- `incident_confirmed` → withdraws/holds authority (this pattern preceded
  real incidents)
- Source: resolution_records, incident validation, adjudication verdicts

### 3.4 The replay corpus as bootstrap (one-time)

The 500k+ replayed jobs with known outcomes are Cascade's validation set:
- Historical self-resolving patterns → suppression-authority candidates with
  ground truth
- Historical incident-correlated patterns → hold-out set proving suppression
  would NOT have hidden them
- Cascade's own `cascade-replay` path is the intended bootstrap mechanism

---

## 4. What StarGate keeps, what Cascade owns

| Concern | Owner |
|---|---|
| Collection, idempotency, historical truth | **StarGate** |
| Compression, dedup, suppression execution | **Cascade** |
| Suppression *authority* | **Cascade executes, StarGate's outcomes govern** |
| Classification | Cascade heads propose; StarGate taxonomy reconciles; LLM for remainder |
| Investigation, RCA, causal chains | **StarGate** |
| Remediation decisions | **StarGate** (human-gated, always) |
| Memory / federation | Cascade (signal memory) + StarGate (knowledge base) — bridged by investigation citations |
| Real-time watch (<5m) | **Open question** — DeepField today; either absorb into scanner tiers or accept 5m floor |

---

## 5. DeepField sunset path (consequence, not decree)

1. **Inventory dependents**: immutable-ledger wiring, DeepField dashboard
   consumers, Splunk polling consumers — confirm nobody else reads
   deepfield-inferences
2. **Absorb or drop unique functions**: real-time watch (300s) — either a
   scanner tier or consciously dropped; Splunk — adapter into StarGate
   collectors if the signal is still wanted
3. **Migrate the incident push**: DeepField→StarGate incidents are already
   thin; StarGate's own investigations supersede them
4. **Freeze, don't delete**: stop the forward flow, keep the deployment for
   read-back during a transition window, then decommission

**Do not start this until the cascade integration is proven in shadow mode.**

---

## 6. Gating checklist (in order)

1. **Proof-to-OSS pin reconciliation** — cascade-compression (proof, 0.1.0) vs
   cascade-compression-oss (0.2.0rc5) differ; the integration targets the
   artifact intended for qualification. This is the hard gate.
2. **Team adoption of current StarGate** — first MCP calls, first reviews;
   consolidating the intelligence layer mid-début adds risk to both
3. **Archive replay complete** — the bootstrap corpus should be whole
4. **Shadow mode first** — cascade receives the batch feed but its
   classifications/suppressions are advisory-only (tagged, not applied) for a
   full validation cycle; incident-validation methodology applied to
   suppression decisions ("would suppression X have hidden incident Y?")
5. **DeepField dependents inventory** before any sunset motion

---

## 7. Open questions for the review

1. Where does the cascade instance live — co-deployed in the stargate
   namespace, or its own with network policy between?
2. Does the existing cascade Stargate collector (cascade reading StarGate)
   continue, or does the batch bridge replace it (one direction, not both)?
3. The AAP live-collection overlap: cascade's AAP cursors vs StarGate's
   collectors — consolidate on StarGate's spine per §2, or keep cascade's
   for its memory continuity?
4. llm-d-sc (semantic classifier) availability on the RHDP LLM fleet —
   is the gRPC endpoint deployable where cascade runs?
5. Federation: does cascade's memory federation extend beyond infra01, and
   does StarGate's knowledge base join it or stay separate?

---

## 8. Sources

- StarGate audit (2026-10-29): DeepField data flow §3, §2.4 security findings
- cascade-compression (production proof): README, docs/proof-to-oss.md,
  docs/aap-live-collection.md, docs/rhdp-platform-memory.md (Aug 15 report)
- cascade-compression-oss: README (pilot: 92% duplicates), docs/architecture.md
  (nano/classifier/memory governance)
- StarGate replay corpus: partner (18k), prod0 extract+archive (243k),
  event0 (70k) — the bootstrap validation set
