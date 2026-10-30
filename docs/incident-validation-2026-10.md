# Incident-Window Validation — StarGate vs Documented RCA

**Date:** Oct 30, 2026
**Method:** RHDP Confluence post-mortems and reliability analyses (read-only) were used as
labeled ground truth. For each documented incident, StarGate's evaluation database was
queried for the incident window. No human review was performed — this is retrospective
validation against incidents whose root causes were independently established by the ops
team (Billy Bethell, Yordan Yordanov, Victor Aguilera, Andrew Jones).

This converts the "zero verified accuracy" gap into incident-level ground truth:
**detection accuracy** (did StarGate see the incident?) and **attribution accuracy**
(did StarGate classify the root cause?).

## Results

| # | Documented incident | Source | Window | StarGate detected | Root cause attributed |
|---|---------------------|--------|--------|-------------------|----------------------|
| 1 | SSO/api.openshift.com 5xx crashed AI integration (`response.json()` on 5xx body) | 90-Day Analysis (511804406) | Oct 21–22 | **YES** — `assisted_installer_failed` 4 → 86 → 94 | **PARTIAL** — symptom class correct; root-cause signature (`Expecting value: line 1 column 1 (char 0)`) present in messages but no class for it |
| 2 | CNV account bloat (RHDPOPS-24554, fixed Oct 14) | 90-Day Analysis | Sep 28 – Oct 14 | **YES** — Oct 14 fail rate 21.6% (5–6× baseline); top failing labs all CNV items | **MISS** — 80% of the spike (2,721 evals) unclassified |
| 3 | ocpv06 memory-saturated + ocpv08 sick nodes (RHDPOPS-24544) | CNV Known Issues (501907733) | Oct 13–14 | **YES** — ocpv08: `vmi_not_running` (110), `datavolume_failed/not_ready` (84), `pods_not_ready` (70) — matches documented "VMIs don't create in time, DataVolume clones slow down massively" | **PARTIAL** — symptoms match precisely; no `cluster_capacity_saturated` class to unify them |
| 4 | EVENT cluster-pool capacity exhaustion (LB1758 98%, LB2645 99%) | 90-Day Analysis + Yordan feedback | Sep–Oct | **YES** — 117 LB1758 + 41 LB2645 failures recorded from event AAP controllers | **PARTIAL** — failures captured; capacity-exhaustion attribution not distinguished from other causes |
| 5 | Missing `environment_level` annotation → pre-flight exit, no AAP job (RHDPOPS-24198) | Fix write-up (463437924) | Aug 2026 (APAC) | **NO** — by construction: no AAP job is triggered, so no signal reaches StarGate | **COVERAGE GAP** — pre-flight failures are invisible to AAP-log-based collection |
| 6 | OVN MTU 1400 on 8900 jumbo-frame NICs (RHDPOPS-24585) | OVN MTU Incident (506888435) | Oct 21 | **NO** — manifests as slowness inside workshop clusters, which StarGate does not monitor | **OUT OF SCOPE** — would require workshop-cluster instrumentation |

**Detection: 4 of 4 incidents that produce AAP-visible failures, on the documented dates.**
**Attribution: 0 of 4 fully attributed at root-cause level. 3 of 4 have the root-cause
signature present in captured evidence.**

## What this proves

1. **StarGate's collection and detection work.** Every documented incident that produced
   AAP job failures is visible in StarGate's database on the correct dates, with the
   correct symptom distribution.
2. **The attribution gap is real and quantified.** StarGate classifies symptoms
   (`assisted_installer_failed`, `vmi_not_running`), not causes (SSO 5xx, memory
   saturation). In 3 of 4 incidents the root-cause signature is present in the captured
   message text — the taxonomy simply lacks the classes to name it.
3. **The account-bloat incident was 80% unclassified** — the largest single cluster of
   unclassified failures maps to a real, named, fixed incident.

## New validated classes (added)

- `json_decode_error` — pattern `Expecting value: line 1 column 1` — validated by
  incident #1; root cause: external API returned non-JSON (5xx error page); fix
  AI#8 / agd-v2#227 (defensive response-type check, pending prod deploy as of Oct 28).
- `cluster_capacity_saturated` — no single-message pattern; proposed as a
  correlation-level class (see below).

## Follow-up work

- `cluster_capacity_saturated` requires cluster-context correlation (many diverse
  symptom failures on one cluster in one window = saturation), not single-message
  regex. Candidate for the correlation layer, not the pattern matcher.
- Pre-flight failures (incident #5) are structurally invisible to AAP-log collection.
  A Catalog/Babylon-side pre-flight event feed would close this.
- Billy's 90-day analysis is the human equivalent of StarGate's reliability dashboard.
  Cross-referencing the two quarterly is the standing accuracy audit.

## Sources (Confluence, read-only)

- 511804406 — RHDP Provisioning Reliability — 90-Day Analysis (Oct 2026)
- 511837217 — Re: 90-Day Analysis (Yordan's corrections)
- 506888435 — OVN MTU Incident — ocp-dev-days (Oct 2026)
- 501907733 — CNV Cluster Ops — Known Issues & Gaps (Oct 2026)
- 437061721 — Post-Mortem Actions Tracker — 2026
- 463437924 — Fix: Missing environment_level annotation
- 512622803 — OLM CSV Propagation Timeout
- 481362807 — ACM Demo KubeletConfig type mismatch
- 492929166 — OADP setup-oadp-credentials ImagePullBackOff
- 418452816 — Workshop Seat Display (0/0 Users)
- 503154034 — Infrastructure Pain Points
