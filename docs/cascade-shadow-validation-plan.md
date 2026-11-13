# Cascade Shadow Validation Plan

**Status: DRAFT — operationalizes gate #4 of the cascade integration design**
**Author: drafted Nov 12 2026 from the live-audit session (infra01 probes, DB
footprints, incident-validation precedent); requires review by Kershaw**

Related: [cascade-integration-design.md](cascade-integration-design.md) §6
gate 4; [incident-validation-2026-10.md](incident-validation-2026-10.md)
(methodology this plan reuses).

---

## 1. The question this plan answers

> If Cascade's compression tier had been running against StarGate's signal
> flow for the last N days, would its decisions have been **safe**
> (nothing real suppressed) and **useful** (volume down, classifications
> sound, survivors more informative)?

Shadow mode answers this with data before the integration gets any
authority. Nothing Cascade says in shadow is applied; everything is
recorded, tagged, and measurable.

## 2. What already exists to build on

| Asset | Reuse |
|---|---|
| Incident-validation methodology (Oct 2026 study) | The retrospective safety audit: "would suppression X have hidden incident Y?" — same 4/4 documented-incident set |
| Qualification flywheel (frozen case sets, Wilson intervals, ablation) | Head-classification quality measurement — same statistics as the LLM classifier's 91.7% benchmark |
| Replay corpus (partner 18k, prod0 243k, event0 70k; 500k+ total with known outcomes) | Phase 0 backtest ground truth — self-resolving patterns vs incident-correlated patterns |
| Shadow-mode precedent | `_shadow_mode_loop` (auto-LLM calibration shadow) and Cascade's own 5% shadow-disagreement governance — the pattern is proven in both systems |
| Live-audit baseline (Nov 12 2026) | Pre-integration signal rates to measure against: ~1M evidence rows/day, 38 DeepField incidents/day pushed, glx pipeline writing continuously |

## 3. Phase 0 — Backtest on the replay corpus (offline, zero production risk)

**No live feed, no new code in production.** Cascade's `cascade-replay`
path ingests the historical corpus; every suppression/classification
decision is evaluated against known outcomes.

- **Suppression-candidate ground truth**: historical patterns that
  self-resolved (fail→pass with no remediation) are legitimate
  suppression candidates — measure what fraction Cascade would have
  suppressed, and the false-suppression rate against them.
- **Hold-out safety set**: signals correlated with documented incidents
  (the Oct 13–14 ocpv08 saturation, the Oct 21 external-dependency 5xx,
  the incident-validation set). **Any suppression in this set is a
  finding, not a statistic.**
- **Deliverable**: a backtest report with Wilson-interval rates, the
  same format as the classifier qualification card
  (`fabric.evaluation-card/v1`).

**Exit**: backtest reviewed; false-suppression rate on the hold-out set
is zero or each violation understood and traced to a fixable rule.

## 4. Phase 1 — Shadow feed (advisory-only, tagged)

The batch bridge (design §3.1) runs for real, but responses are
**recorded, never applied**:

- New table `cascade_shadow_decisions` (one row per signal per cycle):
  `source_event_id`, `decision` (suppressed / survivor / head_classified),
  `head_classification`, `taxonomy_agreement` (bool, vs the 111-class
  pattern match), `suppression_receipt` (Cascade's decision receipt),
  `batch_id`, `latency_ms`, `created_at`. **No writes to `source_events`
  or `evaluations` in shadow.**
- Degrade contract from day one: Cascade unavailable → passthrough
  classification (current behavior), bounded queue, zero data loss —
  verified by killing the cascade route mid-cycle during Phase 2.
- Batch piggybacks the existing ingest flush (500-record batches).

## 5. Phase 2 — Measurement window

**14 days** of live shadow — long enough to span tier cycles
(5m/15m/1h), weekday/weekend signal shapes, and the DeepField incident
volume (~38/day baseline). Continue normal platform operation
untouched; Cascade sees the full signal flow.

## 6. Phase 3 — Adjudication and acceptance criteria

| Criterion | Threshold | Nature |
|---|---|---|
| Retrospective suppression safety | **Zero** suppressions in the documented-incident hold-out set | Hard gate |
| False-suppression rate (backtest, self-resolved corpus) | Measured, Wilson-intervaled, reviewed per class | Judgment |
| Head-classification vs taxonomy agreement | Measured against frozen case set; disagreements adjudicated by the qualification flywheel (become new evaluation cases) | Judgment |
| Compression rate | Reported honestly: dedup %, suppression %, with the ~46% claim and the pilot's 92%-duplicate observation as priors, not targets | Informational |
| Batch round-trip latency | Within ingest-flush budget (p95 reported) | Operational |
| Degrade behavior | Kill cascade mid-cycle → passthrough, no backlog growth, no lost signals | Hard gate |
| Survivor informativeness | Survivors surface the unclassified repeat-failure pattern (the TARSy trigger concept) earlier than the current queue does | Judgment |

**Adjudication output**: a decision report — proceed to advisory-applied,
extend shadow, or stop with findings — using the incident-validation
report format so the three studies read as one series.

## 7. Observability during shadow

- `GET /admin/cascade/shadow` — counts, rates, disagreement samples,
  latency percentiles (admin-gated like the other shadow endpoints)
- MCP tool `get_cascade_shadow` — the team can query shadow state in
  plain English; doubles as an adoption surface (design gate #2)
- Weekly digest in the existing report format; nothing new to babysit

## 8. Sequencing and the gating checklist

```
gate 1  proof-vs-OSS pin reconciliation   ← HARD PREREQUISITE (which artifact are we validating?)
gate 2  team adoption of current StarGate  ← parallel, not blocking Phase 0
gate 3  archive replay complete            ← strengthens Phase 0 corpus
gate 4  THIS PLAN                          ← Phase 0 can start any time after gate 1
gate 5  DeepField dependents inventory     ← parallel; no sunset motion regardless
```

Phase 0 is the cheap first move: no bridge code, no production changes,
and it can start as soon as the pin question is answered. Phases 1–2
need the batch bridge built (design §3.1) — estimated days, not weeks,
given the ingest-flush batching already exists.

## 9. Honest limits

- **The incident sample is small** (4 documented incidents). The
  retrospective audit is necessary, not sufficient — that is exactly why
  the live 14-day window exists, and why the hold-out set grows with
  every incident StarGate detects going forward.
- **Shadow cannot prove the feedback loop** (suppression authority
  earned/withdrawn by outcomes) — that circuit only exists once
  decisions are applied. The plan measures the *decisions*; the
  authority mechanism ships with its own withdrawal instrumentation and
  stays under review after cutover.
- **Volume asymmetry**: Cascade's own governance runs 5% shadow
  disagreement on its side; this plan shadows 100% of StarGate's flow
  into Cascade. Both directions are tagged; reconciliation of the two
  shadow views is an adjudication input, not a gate.
- **The "Kafka dead 4.5mo" annotation in the design doc is wrong at the
  transport layer** (bootstrap reachable, producer connects — verified
  Nov 12). The batch bridge should use the direct HTTP contract (§3.1)
  regardless; Kafka's role is a separate, small decision.

## 10. Salvage note (TARSy)

The TARSy escalation trigger — *unclassified failure repeated 2+ times
for a lab/cluster deserves prioritized investigation* — is folded into
the survivor-informativeness criterion above rather than revived as an
integration. If shadow shows Cascade survivors already surface this
pattern, the trigger becomes a StarGate-side investigation-queue
priority (pure internal change, no counterparty needed). The June 3
investigation chains (`pods_not_ready`, `pods_crashlooping`,
`service_has_no_endpoints`) remain useful catalog entries independent
of this decision.

---

## Addendum: the auto-remediation calibration study (Nov 13 2026)

Prompted by the first human review session: does the pending-actions
queue's confidence scoring predict whether an action is needed?
Terminal outcomes (11,307 actions) answer it:

| Confidence bucket | Needed (approved) | Self-healed / rejected |
|---|---|---|
| 0.5–1.0 (all sub-1.0) | **0** | 4,658 |
| 1.0 | 21 | 6,419 |

**The 21 approvals are all proof-lab self-tests** (`proof_*` types,
`stargate-test` target). Production remediation approvals: zero, ever.

**Verdict — the current confidence scores do not calibrate.** Every
deepfield-sourced action type (probe_failure, resource_exhaustion,
config_error, network_issue, storage_issue, scheduling_issue — avg
confidence 0.84–0.89) shows zero needed actions across its entire
terminal history: ~96 percent self-healed, the rest dismissed. A 0.89
action is exactly as unneeded as a 0.84 one. Enabling auto-remediation
at ANY threshold on this stream would have produced only wasted
executions.

**What the evidence does support, for when we get there:**

1. **Do not enable auto-remediation on deepfield-sourced actions at
   any confidence threshold** — the stream is ~all transient.
2. **The 10,871 auto-resolutions are suppression ground truth** — the
   same self-healing population Cascade's compression tier exists to
   suppress (Phase 0 measured 46.8 percent dedup on exactly this
   shape). The two loops close on each other: suppression upstream
   prevents the action queue from filling with transients.
3. **Confidence needs re-derivation, persistence-based**: an action
   that survives K scan cycles without self-healing earns confidence;
   the auto_resolved timestamps already hold the survival curves. The
   current one-shot score carries no signal.
4. The proof lab's internal loop (0.95 confidence, admin approval,
   verification evals — 19/20 in the proof matrix) remains the only
   working confidence signal, and it is self-referential by design.

This is the platform measuring its own readiness honestly: the gates
exist, the metrics exist, and the evidence says the metrics are not
ready. That is a finding, not a failure — it is what advisory mode
is for.

### Addendum 2: the survival curve (same day, completing the derivation)

The auto-resolved actions carry their own timestamps
(`proposed_at → reviewed_at`), giving the persistence distribution
directly:

| Time-to-self-heal | Actions | Cumulative |
|---|---|---|
| 0–6h | 8,144 | 75% |
| 6–24h | 1,742 | 91% |
| 24–48h | 498 | 95.5% |
| 48h+ | 497 | 100% |

**Median time-to-self-heal: 56 minutes. Only 9.1% survive 24 hours.**

The derivation the calibration study called for, now with numbers:
**persistence-based confidence = survival past K hours**, and K = 24
is the natural gate — it eliminates 91% of the action queue as
transient while retaining the sick-environment population (the
497 surviving 48h+ are the zt-ansiblebu class). The mechanism is
confirmed by the morning's reviews: the CDI clone window is 10–15
minutes, the startup races sub-hour — the sub-6h bulk IS those
families, already approved as noise-with-condition.

**The recommendation for when we get there**: gate auto-remediation
on 24-hour persistence, not on the current one-shot confidence score.
The data to run that gate already accumulates in every action's
timestamps.
