# Cascade Backtest — Phase 0, Round 1 (Nov 12 2026)

**First offline validation of Cascade's compression decisions against
StarGate's ground truth.** Implements [cascade-shadow-validation-plan.md](cascade-shadow-validation-plan.md)
Phase 0 against the production proof engine (`cascade-compression` 0.1.0 —
the artifact deployed on infra01). Harness: `scripts/cascade_backtest.py`
(stdlib-only, runs under Cascade's own venv; corpus extracted read-only
from production).

## Method

- **Corpus**: 91,598 failed AAP `source_events` (the full replay corpus,
  Sep 2025 – Nov 2026), 82,392 with usable timestamps, mapped to Cascade
  `Signal`s with the StarGate taxonomy's severities.
- **Execution**: Cascade's real nano pipeline (`default_agents()`:
  TrendDetector, Deduplicate, TransientSuppressor, SeverityGate,
  PatternClassifier, ThresholdClassifier), 59 weekly batches — windowed
  like the live collectors deliver, and bounding the pipeline's
  quadratic per-decision lookup.
- **Ground truth**: the four documented-incident windows (hard gate,
  from incident-validation-2026-10) and 15,525 resolution records
  (self-resolved / namespace-recycled / incident-acknowledged).

## Results

| Metric | Result |
|---|---|
| **Hard gate — incident windows** | **PASS**: zero suppressions, zero drops in all three windows with signals (SSO 5xx: 811 signals / 17 survivors; CNV bloat: 5,386 / 3,231; event pools: 3,353 / 3,163) |
| Compression | **46.8%** — 38,562 of 82,392 deduped; independently confirms the design doc's ~46% claim on real data |
| Suppression | **0** — all compression is dedup; the transient-suppressor's type vocabulary is K8s-native and does not intersect AAP failure classes |
| Classification agreement | **0 / 2,762** — see finding 1 |
| Fail-open safety | **Observed working**: Cascade refused dedupe of high-severity signals (`ec2_capacity_exhausted`, `ansible_playbook_bug`, …) even when the deduper proposed it |

## Findings (what round 1 exists to surface)

1. **The taxonomy reconciliation (design §3.2) is load-bearing, not
   assumed.** Cascade's classifier labels and StarGate's 111-class taxonomy
   share no label names — 0 of 2,762 classified signals agreed. The wire
   format is shared; the vocabularies are not. Integration needs an explicit
   label-mapping layer, and the disagreement set is exactly the input the
   qualification flywheel wants.
2. **The AAP corpus cannot validate runtime incidents or self-resolution.**
   The ocpv saturation incident (Oct 13–14) produced evaluation-stage
   failures (`vmi_not_running`, `datavolume_failed`) with no AAP-corpus
   signals; and the self-resolved ground truth lives in the evaluation
   universe — guid overlap between resolution records and AAP events is 103
   of 5,773 resolution labs, yielding 11 matched signals and zero
   self-resolved windows. Provision failures and evaluation failures are
   different failure domains.
3. **9,206 signals (10%) lack timestamps** — NULL `occurred_at` on some
   replayed records; excluded, noted.
4. **For the AAP domain, dedup IS the compression** — suppression
   contributed nothing. Any suppression-authority expectations for AAP
   signals should be recalibrated accordingly.

## Round 2 (scoped, not yet run)

Build the **evaluation-derived corpus** (failed evaluations as signals:
lab, cluster, stage, failure_class, evaluated_at) and re-run the same
harness. This one corpus closes both coverage gaps: the saturation
incident window becomes testable, and the self-resolved ground truth
joins natively (same universe). The same harness also runs the
`cascade-compression-oss` (0.2.1rc1) engine over both corpora for the
empirical pin reconciliation (design gate #1).

## Honest limits

- Round 1 validates the **proof engine** (0.1.0) only; the OSS comparison
  is round 2.
- Weekly batching bounds cross-week dedup semantics (live collectors
  batch similarly, but the choice is ours, not measured).
- Severity mapping uses the StarGate taxonomy's severities; Cascade's own
  domain packs may map differently.
