# Failure-class taxonomy: one registry, enforced in CI

**Status:** proposal
**Owner:** StarGate (schema), with AgnosticV / Babylon as consumers
**Measured:** 19 November 2026, production registry and 30 days of evaluations

## The finding

The platform publishes one set of failure classes and emits another.

| Measure | Count |
|---|---|
| Classes in `GET /api/failure-classes` (8 YAML sources) | 115 |
| Classes defined inside rubrics (`rubrics/**/failure_classes`) | 41 (7 overlap) |
| Union of the two | 149 |
| Distinct classes emitted in 30 days — events and evaluations | 52 |
| Published classes observed in 30 days | 25 |
| Published classes never observed in 30 days | 90 |
| — matcher-only classes with zero matches | 66 |
| — proof-proven but never seen in production | 19 |
| — rubric classes that never fired | 5 |
| Emitted classes **absent** from the published registry | 27 |
| — covered by a rubric instead | 16 |
| — defined **nowhere** | 11 |
| Evaluations landing in `unclassified` | 12.7% (12,332) |

The eleven that exist nowhere are synthesised at runtime:

- `engine/rubric_evaluator.py::_classify_entry_failure` maps entry-criterion
  names to classes (`deployment_exists` → `deployment_missing`) and falls back
  to `f"{criterion_name}_failed"`.
- `collectors/credential_health.py`, `collectors/llm_health.py` and
  `contracts/outcome_contracts.py` emit their own names.
- `unclassified` is a deliberate fallback, but nothing counts it as a gap.

Examples seen in production but missing from the registry: `datavolume_not_ready`,
`datavolume_missing`, `deployment_missing`, `guest_agent_not_connected`,
`model_endpoint_error`, `namespace_missing`, `showroom_not_ready`,
`service_missing`, `vmi_not_running`.

**Attribution, not definition, is the real gap.** 90 of the 115 published
classes had no event or evaluation in 30 days: 66 are pattern matchers that
matched nothing, 19 are proof-proven but never seen in production, and 5 are
rubric classes that never fired. Of the 25 published classes that *were*
observed, 24 have no fault-injection proof and one does.

**Data-quality note.** `event_log.failure_class` also contains comma-joined
lists (`"datavolume_missing, namespace_missing, vmi_not_running"`) on 127 events
in 30 days. That inflates distinct-class counts and breaks any `group by`. The
generator should split, or the emitter should write one row per class.

## Why it matters

1. **Cross-team reporting is unsafe.** Two teams can quote class-level counts
   that do not refer to the same registry.
2. **Agents cannot look up what they classify.** An investigation that emits
   `datavolume_not_ready` gets no remediation, severity or owner from the
   catalogue.
3. **Proof coverage cannot be compared to production.** Of the 20 classes in
   the proof matrix, 19 had zero occurrences in 30 days — events or evaluations
   — and the one that fired accounts for 0.01% of evaluations. Without a shared
   key, "19 of 20 proven" cannot be turned into "what fraction of real failures
   is proven".
4. **Noise analysis is distorted.** `unclassified` absorbs 12.7% of
   evaluations; a shrinking registry makes the platform look better than it is.

## Proposal

**One generated registry, checked in CI.**

1. **Generate.** Build `failure-classes/registry.yaml` from the three emitters:
   the eight YAML sources, rubric `failure_classes` blocks, and the explicit
   maps in `rubric_evaluator.py` and the collectors. Generation is deterministic
   (sorted, no timestamps).
2. **Serve.** `/api/failure-classes` returns the generated registry, not a scan
   of the YAML directory. Every entry carries `source`, `severity`, `owner`,
   `remediation` and whether it is `emittable` by a rubric or collector.
3. **Guard.** Add a CI check that fails when:
   - an emitted class (rubric, collector, or `_classify_entry_failure` target)
     is absent from the registry, or
   - a registry entry has no emitter and no pattern (dead class), reported as a
     warning with an explicit allowlist.
4. **Count the fallback.** Treat `unclassified` as a metric with an alert
   threshold, not a class.

## Acceptance criteria

- [ ] `make taxonomy` regenerates the registry with no diff on a clean tree.
- [ ] API count equals registry count; a test asserts every rubric class is present.
- [ ] CI fails on a new unregistered class (verified with a throwaway rubric).
- [ ] A `taxonomy-drift` report lists emitted-but-unregistered and
      registered-but-unemitted classes per release.
- [ ] `unclassified` share is on the dashboard with a threshold.

## Effort

Small. Generator plus test is roughly a day; the CI guard is a second day.
No runtime behaviour changes — only the published surface and the check.

## Related

- `docs/investigation-workflow.md` § proof cycle
- `docs/pitch-kit.md` Q5 — "injected classes", not "classes"
- `failure-classes/*.yaml`, `rubrics/**/*.yaml`
- `engine/rubric_evaluator.py::_classify_entry_failure`
