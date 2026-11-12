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

---

## First gate evaluation (Nov 13 2026) — FAIL, authority correctly withheld

Run against both documented capacity incidents with real evidence
(Labagator's actual sessions, 316 catalog profiles, the observed-peak
supply ceiling):

| Incident | Sessions in window | Forecast said | Crossing | Verdict |
|---|---|---|---|---|
| ocpv08/06 saturation (Oct 13–14) | 4 | **green** | none | false green |
| event-pool exhaustion (Sep–Oct) | 57 | **green** | none | false green |

**Gate verdict: fail (red) — promotion not eligible.** Both false
greens, and the mechanisms are now understood:

1. **The saturation incident is supply-side degradation** (memory-
   saturated and sick nodes), not session-demand shock. A demand
   forecast cannot see it by construction — that class belongs to the
   saturation detector (validated 4/4 in the incident study). Either
   the forecaster integrates a cluster-health supply factor, or its
   authority scope explicitly excludes supply-degradation incidents.
2. **The event-pool exhaustion is placement-specific**: LB1758/LB2645
   were individual event pools, and the fleet-aggregate demand/supply
   comparison masks pool-level exhaustion by construction. Earning
   authority on this class requires the per-pool join (the placement
   question deferred from Phase 1).

This is the gate working as designed: authority withheld on evidence,
the model gaps named precisely, and the advisory state enforced
structurally. The increment list for a future promotion attempt:
per-pool placement join; cluster-health supply factor or an explicit
scope declaration; then forward-accuracy accumulation (A-track, already
persisting every cycle).

---

## Second gate evaluation (Nov 13 2026, later) — the event-pool class PASSES

The first evaluation named the gap: fleet-aggregate demand masks
pool-level exhaustion. The per-pool join was built
(`engine/pool_demand.py`) from data StarGate already collects —
Labagator sessions joined to lab records carrying `deploy_limit`
(concurrent environment slots), occupancy snapped outward to hour
boundaries — and re-run against the same incident:

| Pool | Limit | Peak occupancy | State | Crossing | Knowable since |
|---|---|---|---|---|---|
| LB2645 | 11 | **23 (209%)** | **deficit** | Sep 30 15:00 | **Aug 27** |
| LB1758 | 15 | 15 (100%) | at_limit | — | Aug 27 |

**The event-pool exhaustion is flagged with 816.6 hours (34.0 days)
of lead time** — the demand was schedulable knowledge from session
creation. The projection also surfaced five additional oversubscribed
pools in the same window (LB2391 23/10, LB2596 15/12, LB2236 23/15,
LB2865 15/10, LB2862 23/20) that the incident record never named —
candidates for validation, and exactly the early-warning class the
forecaster exists for.

The ocpv saturation remains a false green — correctly: it is supply-
side degradation, structurally invisible to a demand forecast. The
evidence now supports the scope declaration: **the forecaster earns
demand-shock authority (demonstrated 34-day lead time); the saturation
detector owns supply-degradation (validated 4/4).** Gate verdict
remains fail overall until the scope is formalized or a
cluster-health supply factor is built.

Live-run bug found and fixed en route: `deploy_time_hours: '0.25'`
(a 15-minute session) produced zero-width spans that matched no hour
boundary and hid the deficit — spans now snap outward to hour
boundaries, with regression tests for both the 0 and sub-hour cases.

---

## First forward pass (Nov 13 2026) — the catch that was a data-quality finding

The forward projection flagged seven RHSC pools for Nov 17 at up to
350 percent (70 attendees vs 20-slot limits). Investigation, with the
user's data-hygiene hypothesis confirmed and sharpened:

1. **The labs were never AgnosticV-synced at all** — `last_synced:
   None`, `agv_validation: None` on every RHSC lab, and the catalog
   item (`ocp-virt-roadshow-2026`) declares no limits. The
   deploy_limits are hand-entered Labagator values with no upstream
   source: folklore, not drift.
2. **The sessions carry event-total attendance on every room** — one
   event (id 46), 11 rooms all 08:00–18:00, 70 stamped on each: 770
   "concurrent demands" in the data for ~70 rotating people. Roadshow
   semantics are absent from the session model.

Model fix shipped: sessions sharing (event_id, date) are one cohort —
fleet-level demand counts the cohort once (118 over the 7-day window,
not 770). Per-room deficit states remain naive BY DATA LIMIT: the
rotation schedule (which room hosts which subset when) is not in
Labagator, so per-room concurrency is unknowable from current data.
Advisory mode did its job — the false alarm was free, and it exposed
two concrete data-hygiene debts: RHSC limits need real sources, and
roadshow events need cohort semantics.
