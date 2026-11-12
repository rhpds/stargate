# Capacity Forecaster Plan

**Status: DRAFT — for review; phases 1–2 are days-scale, not weeks**
**Author: drafted Nov 12 2026; grounded in the live code audit (projector,
collectors, constraint loader) and the documented capacity incidents**

Related: [cascade-shadow-validation-plan.md](cascade-shadow-validation-plan.md)
(signal-quality input), [incident-validation-2026-10.md](incident-validation-2026-10.md)
(validation methodology), Friday's retention release (Phase 3 rides it).

---

## 1. The objective

Turn the existing pool-level capacity projector into a **resource-level
capacity planner**: not just "pool X exhausts at 14:00" but "ocpv08 is short
N vCPU and M GiB at 14:00 given the session schedule" — with measured
forecast accuracy, the same way incident detection accuracy was established.

## 2. What exists today (verified in code, not aspiration)

| Piece | Where | State |
|---|---|---|
| Workload-aware projector (hourly demand vs supply, bottleneck pools, risk level) | `engine/capacity_projector.py` | Working; 6h window; weighted units (attendees × complexity) |
| Pool supply + recycling velocity | `engine/pool_velocity.py`, Poolboy collector | Working |
| Session demand (schedule, attendee counts) | Labagator collector | Working |
| **Per-lab resource specs — CPU, memory, instance counts** | `constraints/agnosticv_loader.py` (`worker_instance_count`, `ai_workers_cores`, `ai_workers_memory`) | **Parsed today, used only for violation checks — not wired to the projector** |
| Node supply (CPU, hot nodes, VMs/node) | scanner tier-1 | Working, persisted as evaluations |
| Storage supply (Ceph headroom, pending PVCs) | scanner tier-1b | Working |
| Saturation detection (rate spike + diversity + differential) | `engine/cluster_saturation.py` | Validated on the Oct 13–14 incident — reactive, not predictive |
| Capacity API + dashboard | `/capacity/*`, CapacityPage | Working; page lacks loading/error states |

## 3. Phases

### Phase 1 — The resource-level join (days)

Map catalog item → declared resource profile (from the already-parsed
AgnosticV specs; complexity score remains the fallback for items without
declared resources) and extend `project_capacity` to project **resource
units** (vCPU, GiB, VM slots) per cluster per hour, alongside the existing
weighted demand. Supply side joins the tier-1 node metrics already
persisted. Output: per-cluster hourly resource curves and deficit hours.

### Phase 2 — Forecast window, persistence, and accuracy (days)

- Window 6h → 72h (event planning horizon), recurring sessions included.
- Persist hourly projections (new `capacity_forecasts` table) so that
  **forecast accuracy becomes measurable**: predicted bottleneck vs actual,
  reported with Wilson intervals like every other platform measurement.
- **Retrospective validation set — the acceptance gate**: would the
  resource-level projection have flagged (a) the ocpv08/ocpv06 saturation
  of Oct 13–14 and (b) the EVENT pool exhaustion (LB1758 98%, LB2645 99%)
  of Sep–Oct, with lead time? These are the two documented capacity
  incidents; the incident-validation method applied to forecasts.

### Phase 3 — Utilization history (rides the retention release)

Retain node/pool utilization time-series at monthly depth (the bounded,
advisory-locked cleanup pattern from the retention release). This is what
converts "declared specs" into "measured consumption" — over-provisioning
becomes visible, and trend-based growth projection becomes possible.
Utilization snapshots are small; this is retention *policy*, not new
collection.

### Phase 4 — What-if and trend forecasting

`POST /capacity/what-if` (added nodes, moved sessions, changed profiles)
over the same model — parameterized projection, no new collection. Trend
forecasting from the Phase 3 history for procurement-grade horizons.

## 4. Acceptance criteria

| Criterion | Nature |
|---|---|
| Retrospective: both documented capacity incidents flagged with lead time | Hard gate (Phase 2 exit) |
| Forward: forecast accuracy measured and reported per forecast cycle | Standing metric, not a threshold |
| Resource deficits stated in real units (vCPU/GiB/VM slots) per cluster-hour | Definition of done, Phase 1 |
| Forecasts are advisory only — they recommend, humans decide | Invariant (platform-wide) |

## 5. Honest limits

- **Declared specs ≠ measured usage** until Phase 3 lands; the demand side
  starts as requests-based, which over-states real consumption.
- **Profile drift**: AgnosticV sync is manual today (webhook sync is a
  roadmap item); stale profiles degrade the demand curve silently — the
  forecast-accuracy metric is what catches it.
- **Schedule coverage bounds the demand side**: ad-hoc sessions not in
  Labagator are invisible to any forecast.
- **The saturation detector stays** as the safety net — forecasts are
  probabilistic, detection is factual. Neither replaces the other.
- Signal quality matters: 45% of failure volume is `showroom_not_ready` of
  unknown status; the Cascade integration (shadow plan, separate track)
  cleans failure-rate-derived demand signals but is not a prerequisite.

## 6. Sequencing

Phase 1 → 2 are one coherent PR-sized effort (the join + persistence +
the retrospective gate). Phase 3 is a config/retention change riding
Friday's release pattern. Phase 4 follows once accuracy is being measured.
The one-env-var alert wiring (Slack) makes any of this reach humans —
still the cheapest unconnected value in the platform.
