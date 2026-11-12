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

## Round 2 (Nov 12 2026 — executed same day)

Built the **evaluation-derived corpus** (642,463 stratified failed
evaluations: all resolution-linked labs + the incident windows + a 5%
baseline sample) and ran the **full 2×2 engine matrix** — both corpora
through both engines, completing the empirical pin reconciliation
(design gate #1).

### The matrix

| Compression (all dedup; suppression = 0 in every cell) | AAP corpus (82–92k) | Evaluation corpus (579–642k) |
|---|---|---|
| **proof 0.1.0** (deployed) | 46.8% | 59.0% |
| **OSS 0.2.1rc1** | 52.7% | **84.7%** |

### Hard gate: PASS in all six runs

Zero suppressions, zero drops, survivors retained in every incident
window, both engines, both domains. The ocpv-saturation window —
untestable in round 1 — is now covered and passes (proof: 237 signals /
40 survivors; OSS: 264 / 49). The SSO-5xx window shows the design intent
working precisely: ~800 repeated `json_decode_error` evaluations
collapsed to **5 canonical survivors** — the incident signature is
preserved while the repetition noise is compressed.

### Round-2 findings

1. **The pin difference is real and large.** OSS compresses materially
   more than the proof (52.7% vs 46.8% on AAP; **84.7% vs 59.0%** on
   evaluations — 543,847 of 642,462 deduped). Both pass the safety gate,
   but the two artifacts would front the pipeline with very different
   profiles. Gate #1 is now answerable with data: the choice is a
   compression-posture decision (conservative vs aggressive), not a
   safety decision.
2. **Suppression never engages on either domain** — 0 suppressed in all
   six runs. The compression story is entirely dedup; the
   suppression-authority governance machinery is untested by these
   corpora (its types are K8s-native). The self-resolved ground truth is
   now joinable (158–170 signals matched by lab) and confirms it: 0
   suppressed. Suppression validation needs the live shadow phase or
   K8s-domain signals.
3. **Harness portability finding**: the proof's Python 3.9 venv cannot
   parse ~10% of the corpus timestamps that Python 3.11 (OSS venv)
   parses — proof-run totals are ~90% of corpus. Conclusions hold on
   both signal sets, but exact per-cell comparability requires
   timestamp normalization (fix noted for the next harness revision).

### What this means for the review

- The safety question ("would compression hide documented incidents?")
  is answered **no, six times over**, including the saturation incident
  that round 1 could not test.
- The pin question is answered **empirically**: the artifacts differ by
  up to 25.7 compression points on the same corpus; pick the posture,
  then qualify that artifact (per Cascade's own AGENTS.md: local pilot
  results are not qualification of the public artifact).
- The vocabulary mismatch (round 1, 0/2,762) still stands as the
  load-bearing integration work regardless of which engine is chosen.


## Honest limits

- Round 1 validates the **proof engine** (0.1.0) only; the OSS comparison
  is round 2.
- Weekly batching bounds cross-week dedup semantics (live collectors
  batch similarly, but the choice is ours, not measured).
- Severity mapping uses the StarGate taxonomy's severities; Cascade's own
  domain packs may map differently.
