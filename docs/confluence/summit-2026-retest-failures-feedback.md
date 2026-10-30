# Summit 2026 Retest — Next event failures / feedback
# Confluence ID: 491356483
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/491356483

Living tracker — add failures and product feedback during Retest. Carry into RH1 / next Summit / Connect. See #20 + RH1 monitoring section for the 2–3 Oct Anarchy/reporting teardown jam. Parent: Ops Runbook .

 CRITICAL (Wed 30 Sep Retest) — not pinned to ocpv09 
 Workloads landed where we did not expect. Summit Retest was assumed pinned to ocpv09 via event.yaml — it was not. Alberto: pin only existed for roadshow / a few AGV bases ( ocp-virt-roadshow-2026 , ocp-virt-labs-pool , ocp-infoscale-multisno-base ), not the broader Summit catalog.
 Impact: Retest traffic hit shared / production-facing capacity instead of the isolated ocpv09 pool — production affected; several Retest deploys struggled / failed under wrong placement.
 Fix PR: agnosticv#28356 — merged 30 Sep → Babylon sync → redeployed Thu / Fri. Tracker row #8 (DONE). Also on the Ops Runbook .

 Keep rows short. Status: OPEN · DONE · WON'T .
 Backlog
 #
 Item
 Area
 Status
 Notes

 1
 Flow QA needs a per-day option — not run the whole event at once
 Flow
 OPEN 
 Operators need Catalog → Setup → Healthy scoped to one floor day (match Ops Floor day pin). Event-wide QA1→QA3 is too heavy / noisy for multi-day events.

 2
 Auto-test landing page — known URLs and workshop passwords
 Landing
 OPEN 
 Feature request: after landings publish, automatically verify summit landing loads, workshop links resolve to expected Babylon /workshop/… URLs, and passwords match what Flow/event knows (spot-check B1/B2 without hand clicking).

 3
 LB1464 — deployed without S4 fix; redeploy needed
 Babylon
 DONE 
 AGV pin shipped: agnosticv#28348 (merged) — core_workloads → 3e61450 (S4 fix from GPTEINFRA-18050 / core_workloads#185). Ops: redeploy Retest sessions; verify 18072 / 18073 . 18050 / 18072 / 18073 all Closed/Done. 

 4
 LB1088 Code Red — The Breach Challenge! (CNV) — same S4 miss; redeploy needed
 Babylon
 DONE 
 Same pin PR agnosticv#28348 (merged). GUID 030a94c3-e40b-5a66-87a8-6a9bfea9e625 · job 74002 . Ops: redeploy; verify GPTEINFRA-18070 (Closed/Done). 

 5
 Tenant labs AGV — wire meta.sandbox_host so Babylon creates TenantClusterPools
 AGV
 DONE 
 Fixed: agnosticv#28347 (merged) — sandbox_host from cluster-config JSON (+ lb2860 lab label typo). Unblocked sandbox_openshift_* injection for Summit tenant labs.

 6
 Flow — check AGV for tenant / sandbox requirements before deploy
 Flow
 DONE 
 Already does this — Flow warns / gates on tenant pools vs letting Babylon handle. Not a Flow gap; Retest miss was missing AGV sandbox_host (#5). Remaining hardening is Babylon (#7).

 7
 Babylon — better handling when tenant labs lack sandbox_host / TenantClusterPools
 Babylon
 OPEN 
 Follow-up from #5. Fail loud early, or auto-derive sandbox_host from cluster-config, so provision does not proceed without pools / sandbox_openshift_* injection — even if Flow warning is skipped.

 8
 CRITICAL — Summit labs not pinned to ocpv09 — Retest landed on wrong clusters
 AGV
 DONE 
 Wed 30 Sep finding (Patrick / Billy / Alberto). Expected ocpv09 pin in Summit event.yaml s — missing for most Summit catalog. Fix PR: agnosticv#28356 (merged 30 Sep) — pins ocp-cluster-cnv-pools/event.yaml + lab event sandboxes. Production impact: Retest sessions on shared/prod-facing capacity. Retest impact: deploys struggled under wrong placement. After merge: Babylon sync → redeployed Thu/Fri. Why we retest.

 9
 agnosticv event.yamls
 using the event.yaml for an item does not guarentee that the sandbox-api selector is actually events.
 https://github.com/rhpds/agnosticv/blob/master/agd_v2/ocp-cluster-cnv-pools/event.yaml#L25 agd-v2.ocp-cluster-cnv-pools this points to prod

 10
 Summit tenant labs — 2 recovered, 3 still fail in-workload (LB1758 / LB2645 / LB2863)
 Babylon
 OPEN 
 Billy, 1 Oct — live verify on ocp-us-west-2. After #5 ( agnosticv#28347 , merged 30 Sep ~05:04 UTC) the sandbox binding works and tenant labs now pin to ocpv09 . LB2596 & LB2391 now deploy OK. LB1758, LB2645, LB2863 still fail — but in the Ansible workload stage on a correctly-pinned ocpv09 sandbox (sandbox-API HTTP 200, sandbox_openshift_* injected), not a pool/pin issue → per-lab content bug. The Retest 100%-fail was because #5 merged after those deploys ran (20:30 Sep 29 – 01:37 Sep 30 UTC). Babylon fail-loud angle = #7. Root causes isolated & handed over (1 Oct): LB1758 GPTEINFRA-18139 (llamastack image pull denied + route lookup bug), LB2645 GPTEINFRA-18140 (nested AAP2 Controller unreachable), LB2863 GPTEINFRA-18141 (DevSpaces operator install timeout). All three still New / To Do (23 Oct) — content fixes outstanding. Detail + evidence: tenant-lab handover page .

 11
 ocpv08 appears degraded — disproportionate provision failures
 Ops
 OPEN 
 Even now-healthy labs (LB2391, LB2596) fail specifically when a claim lands on ocpv08 ; across Retest many CNV labs (AAP Roadshow 01/02/03, USBGuard, Satellite Basics, SELinux 101, RHEL Troubleshooting Pt 1–5) failed disproportionately on ocpv07 / ocpv08 while succeeding on ocpv01 / ocpv02 . Recommend health-check / drain ocpv08 (and review ocpv07 ) before the next event.

 12
 LB1559 AI/ML Lifecycle at the Edge — flaky / high provision-failure
 Babylon
 OPEN 
 ~50% provision failures scattered across ocpv01/02/07/08 during Retest. LB1839 (Beyond the Basics, OCP Virt) similar (15 fail / 18 success on ocpv01). Root-cause once the pin (#8) + cluster health (#11) settle, then redeploy to confirm.

 13
 Follow-the-sun comms didn't work at Retest — treat the next event as a proper Summit
 Process
 OPEN 
 Around-the-sun / global coverage and shift handoffs did not function as expected during Retest. Review on-call rotation, the handoff doc, comms channels and the escalation path so the next event runs with full Summit-grade coverage — staffed regional shifts (NA / EMEA / APAC), soundcheck, and a clear escalation chain rather than ad-hoc hand-offs.

 14
 LB2861 — Introducing llm-d (AWS) — no AWS GPU capacity, deploy failed
 Ops
 OPEN 
 Wed 30 Sep Retest. summit-2026.lb2861-introducing-llm-d-aws — infra-aws-capacity-reservation could not create an on-demand capacity reservation for 1× g6.12xlarge in us-east-1 : InsufficientInstanceCapacity across all AZs (1d/1c/1a/1f/1b), reservation cr-0804927cf02cbc62f canceled, no fallback region. AWX job 100070 . Pre-reserve GPU capacity / allow alt instance type or region before next event.

 15
 LB2860 private MaaS tenant — missing openshift_cluster_admin_token , cluster can't onboard to sandbox API
 Babylon
 WON'T 
 1 Oct — Johnathan Kupferer, ocp-us-west-2 (event cluster). babylon-tenant-cluster-pool-manager error: openshift_cluster_admin_token missing from provision data → cluster can't be onboarded into sandbox API. Likely cluster admin service account vars not set. Nate Stephany: not released after Summit, replacement item shipped: agnosticv#28372 (merged 2 Oct). No fix needed on this item.

 16
 AnarchyRun queue flood — provisions stuck "queued", 2nd job never kicks off
 Babylon
 OPEN 
 2 Oct — Billy. Two Summit 2026 provisions stuck: lb1464-unified-devsecops-delivery-aws (event-vg2wn, AWX job 75880 ) stuck 4+ hours with 2nd job never kicking off; lb2144-agentops-ocp-cnv (event-59df6) stuck next morning. Root cause: AnarchyRun queue flood — 9,434 queued runs in babylon-anarchy-2 , components fighting over stop timestamp blocked runner pods. Johnathan Kupferer manually kicked AnarchyRun from queued → pending to unblock. Platform bug: GPTEINFRA-18111 (Anarchy endless update loop). The loop showed up as Anarchy -update- runs; last week's code fix was in Babylon tenant-cluster-pool-manager vs workshop-manager stop-timestamp conflict — babylon#3827 (29 Sep), babylon#3834 (1 Oct), babylon#3840 (v0.1.4, 2 Oct). Shipped west as Babylon v0.44.8: infra#1750 / infra#1751 . No rhpds/anarchy PR in that window. Update (23 Oct): GPTEINFRA-18111 now Closed/Done — stop-timestamp update-loop fix shipped (Babylon v0.44.8). Ask still OPEN: monitoring / alerting when AnarchyRuns sit "queued". Follow-through 3 Oct: canceled-run backlog drained as part of #20; monitoring ask still OPEN — see RH1 section.

 17
 Q3 soundcheck not wired up — needs Andrew
 Soundcheck
 OPEN 
 2 Oct — Billy. Q3 soundcheck was not connected up for the next event. Needs Andrew's help to wire it in before Devoxx Belgium / OSS Prague. Ensure soundcheck runs are gated into the pre-event checklist (#13 process gap).

 18
 Move QA logic from Flow → Labagator — Flow should be pure deploy
 Flow / Labagator
 OPEN 
 2 Oct — Billy. QA actions currently embedded in Flow code make Flow do two jobs. Proposal: extract all QA logic into Labagator so Flow is purely a deploy tool — simpler, easier to reason about. Phase 1: QA action buttons in Labagator UI (manual trigger, replaces Flow-driven QA steps). Phase 2: Labagator auto-polls QA status on items that are not yet complete — periodically re-checks and surfaces failures without ops needing to manually re-run, making the QA loop seamless end-to-end.

 19
 CRITICAL — Anarchy operator OOM / recursion bug causing 27k+ run queue flood — all provisions blocked
 Babylon
 OPEN 
 2 Oct — Billy (live incident, ocp-us-west-2 / babylon-anarchy-2). Anarchy operator pod anarchy-77945f6548-rxqt6 OOM-killed at 04:58 UTC (exit 137) after hitting infinite recursion in the run cleanup path:
 anarchyrun.py:333 handle_resume → anarchysubject.py:692 remove_run_from_status → set_active_run_pending (loops)
 Pod has restarted 6 times (last restart 05:00 UTC). After each restart the operator floods the queue — creating ~2 new update runs/second for pool subjects ( ocp-cluster-aws-pools , ocp-cluster-cnv-pools , ocp-virt-labs-pool ) while existing runs are never cleaned up. Queue measured at 27,082 queued runs at 12:10 UTC and growing. All new user provisions (Devoxx Belgium, OSS Prague shared-cluster labs) blocked behind the backlog.
 The generating cause for those update runs is GPTEINFRA-18111 (see #16 PRs). The operator OOM/recursion path itself still has no last-week PR in rhpds/anarchy .
 Needs platform team: 
 Confirm tenant-cluster-pool-manager v0.1.4 / Babylon v0.44.8 is on west (stop-timestamp conflict)

 Fix recursion bug in anarchyrun.py / anarchysubject.py if still present after 18111

 Add monitoring / alerting so this is caught before 4+ hour impact (see also #16)

 Ops follow-through 2–3 Oct (#20): canceled AnarchyRuns drained (~42k → tens); Anarchy list/reconcile recovered; stuck destroys cleared. Alerts still OPEN.
 Update (23 Oct): GPTEINFRA-18111 now Closed/Done (generating update-loop cause resolved via Babylon v0.44.8). Still OPEN: verify the operator OOM/recursion path does not reproduce after 18111, and alerting.

 20
 CRITICAL — Post-Retest teardown jam — AnarchyRun backlog + reporting finalizer deadlock + leftover TenantClusterPools
 Ops / Babylon / Reporting
 DONE (ops) 
 OPEN (mon) 
 2–3 Oct — Patrick (west / babylon-anarchy-2 + demo-reporting ). Full write-up below. Started as Icinga TenantClusterPool CRITICAL after Retest teardown; exposed Anarchy wedged on ~42k runs and reporting unable to finish claim/subject deletes. Generating bug: GPTEINFRA-18111 — last-week PRs babylon#3827 / #3834 / #3840 , shipped infra#1751 (Babylon v0.44.8). Ops drained backlog and unblocked teardown. Update (23 Oct): GPTEINFRA-18111 now Closed/Done — platform fix landed. RH1 still needs monitoring (section below).

 Incident write-up — Anarchy + reporting teardown jam (2–3 Oct)
 Carry into RH1. Same failure mode will block mass destroy / pool teardown during the next event if AnarchyRun volume or reporting↔Anarchy finalizer waits are not watched.

 Platform bug / PRs (week of 29 Sep–2 Oct)
 The jam looked like Anarchy was broken because the commune filled with -update- AnarchyRuns. Ticket: GPTEINFRA-18111 — Anarchy endless update loop on some items (Johnathan Kupferer). Now Closed/Done (~13 Oct). 
 What actually changed last week: babylon-tenant-cluster-pool-manager was fighting workshop-manager over the ResourceClaim stop timestamp. Each fight made Anarchy schedule another update run. There was no PR in rhpds/anarchy between 28 Sep and 5 Oct (no commits there either).
 redhat-cop/babylon#3827 (merged 29 Sep) — do not manage cluster ResourceClaim stop timestamp when the claim belongs to a workshop; tenant-cluster-pool-manager v0.1.3

 redhat-cop/babylon#3834 (merged 2 Oct 00:05 UTC) — detect workshop via WorkshopProvision name label; set Workshop id label from tenant-cluster-pool-manager

 redhat-cop/babylon#3840 (merged 2 Oct) — helm pin tenant-cluster-pool-manager v0.1.4 

 rhpds/infra#1750 — Babylon v0.44.8 to integration

 rhpds/infra#1751 — Babylon v0.44.8 production (“Fix babylon-tenant-cluster-pool-manager conflict over stop timestamp”)

 Confirm v0.44.8 / manager v0.1.4 is what west is running before RH1. Operator OOM/recursion in #19 is a separate Anarchy-operator failure mode and still has no matching last-week Anarchy PR.
 How it showed up
 Icinga — [TenantCluster] Pool Placements west : enabled pools with available clusters 0 < minClusters 1 , plus ResourceClaims pending >30m.

 Two leftover event pools still enabled=true / minClusters=1 after Retest teardown:
 summit-2026.ai-lightning-labs-cluster.event (Summit retest — should have been disabled)

 agd-v2.ocp4-getting-started-cluster.event 

 Deleting pending ResourceClaims alone did not help: pools recreated claims to satisfy minClusters . Setting minClusters=0 stopped recreation; claim deletes then stuck on finalizers.

 Root cause chain (three layers)
 A. Anarchy jammed on AnarchyRun volume ( babylon-anarchy-2 ) 
 Follow-on from #16 / #19 (stop-timestamp update-run flood + operator OOM/recursion) + mass Retest destroy.

 Measured ~42,000 AnarchyRuns ; sampled pages were ~99% runner=canceled (mostly -update- flood leftovers).

 Anarchy operator was alive but wedged : continuous GET …/anarchyruns → API 504 Timeout . Full oc get anarchyrun hung; chunked limit=1 still worked ( remainingItemCount ).

 Subjects sat in destroy-pending / destroying / destroy-complete with anarchy.gpte.redhat.com/subject finalizers. Many destroy-pending still had a canceled provision as activeAction , so destroy never started.

 B. Reporting operator jam / teardown deadlock 
 demo-reporting had been unhealthy earlier on 2 Oct (unjammed via API/worker/operator redeploy — Celery recovered: 8/8 workers pong, queues empty, tasks flowing).

 After that, reporting was not CPU-jammed, but teardown stayed blocked by a cross-controller wait :
 ResourceClaims terminating with only demo.redhat.com/reporting .

 Reporting-operator logs: "Waiting for AnarchySubject finalizers to be removed" before dropping the claim reporting finalizer.

 Subjects had demo.redhat.com/reporting-deletion=true + reporting-task-published , but only held anarchy.gpte.redhat.com/subject — Anarchy could not finish delete while it could not list/process runs.

 Net: reporting waits on Anarchy subject finalizers; Anarchy cannot clear subjects/runs while AnarchyRun list times out. Looks like "reporting hung" even when Celery is idle.

 C. Leftover enabled TenantClusterPools 
 Event-scope pools left enabled after teardown kept trying to warm clusters → pending claims → more Anarchy work → Icinga noise.

 What we did (ops)
 Set leftover event pools minClusters=0 (stop claim recreation).

 Deleted terminating claims (then hit reporting/Anarchy finalizer wait).

 Drained canceled AnarchyRuns in babylon-anarchy-2 (paged deletes; expired continue tokens expected under load).

 Deletes alone left objects at deletionTimestamp + finalizer anarchy.gpte.redhat.com . Stripped AnarchyRun finalizers on terminating canceled runs so objects actually left etcd.

 Once backlog fell to tens of runs, Anarchy list/reconcile recovered (no more 504 loop).

 Cleared 29 stuck provision AnarchyActions still active on destroy-pending subjects → they advanced to destroy.

 Stripped subject finalizer on destroy-complete subjects so they could leave; reporting then finished claim finalizers.

 Outcome (3 Oct ~05:20 UTC): ~365 successful runs (normal activity), 0 subjects in destroy-* stuck states, 0 shared-clusters ResourceClaims, event pools still present with minClusters=0 , Anarchy reconciling.

 Still needs platform / product
 ✅ Resolved: Babylon stop-timestamp update-loop — GPTEINFRA-18111 Closed/Done ; v0.44.8 / tenant-cluster-pool-manager v0.1.4 shipped. Still confirm it is what west runs before RH1 ( #16 ).

 Anarchy operator OOM/recursion still needs an rhpds/anarchy fix if it reproduces after 18111 ( #19 ).

 Alerting on AnarchyRun queue depth / age ( #16 ).

 Reporting teardown should not soft-deadlock forever if Anarchy is unhealthy (timeout, escalate, or fail-open with audit).

 Process: disable or delete event TenantClusterPools as part of event teardown (do not leave enabled + minClusters≥1 ).

 RH1 — monitor and avoid this
 Treat the next event ( RH1 ) as Summit-grade for Babylon / Anarchy / reporting health, not only lab content.
 Pre-event / teardown checklist
 Babylon version: west on v0.44.8+ with tenant-cluster-pool-manager v0.1.4 (stop-timestamp conflict fixed).

 TenantClusterPools: after event teardown, confirm event-scope pools are enabled=false or minClusters=0 . Watch Icinga [TenantCluster] Pool Placements on west.

 Do not only delete ResourceClaims on an enabled pool with minClusters≥1 — controller will recreate them.

 AnarchyRun budget: before/during mass destroy, check count in babylon-anarchy-2 (chunked API limit=1 + remainingItemCount if full list hangs). Investigate if canceled/queued runs climb into thousands.

 Anarchy operator health: watch for OOM restarts, and for repeating 504 on AnarchyRun list in operator logs — reconcile is wedged even if pod is Running.

 Reporting ( demo-reporting ): API + workers + operator ready; Celery not backed up. On stuck deletes, check whether logs say Waiting for AnarchySubject finalizers (Anarchy-side) vs Celery/task failures (reporting-side).

 Destroy stalled states: subjects stuck destroy-pending / destroying / destroy-complete beyond 30–60m; AnarchyActions stuck running with canceled provision still active.

 AAP destroy callbacks: many subjects destroying with towerJob started but no completeTimestamp → check event0/event1 job queues.

 Suggested alerts / metrics (need owners)
 Signal
 Why

 AnarchyRun count per commune (esp. babylon-anarchy-2 )
 Catch #16/#19 floods before provisions stall

 Count by runner= label ( canceled / queued / successful )
 Canceled/update flood vs healthy traffic

 Anarchy operator 504 / list latency on AnarchyRuns
 Detect wedged controller

 Anarchy operator restart / OOMKilled
 Recursion/OOM loop from #19

 Subjects in destroy-* longer than N minutes
 Teardown not completing

 ResourceClaims terminating with only demo.redhat.com/reporting 
 Reporting↔Anarchy deadlock

 Reporting Celery queue depth + worker liveness
 True reporting jam vs waiting on Anarchy

 Enabled TenantClusterPools with available < minClusters
 Same Icinga signal that started this

 If it happens again (short runbook)
 Confirm AnarchyRun volume (chunked list). If tens of thousands of canceled runs → drain canceled runs; if deletes stick on anarchy.gpte.redhat.com finalizer while operator is 504'd, strip finalizers on already-terminating canceled runs only.

 Once list works again, clear stuck provision AnarchyActions blocking destroy-pending .

 For destroy-complete stuck only on subject finalizer after infra is done, strip subject finalizer (or fix reporting ack) so reporting can release claim finalizers.

 Disable leftover event pools ( minClusters=0 / enabled=false ).

 Do not grow pool size to "fix" empty pools when claims are stuck pending.

 How to add
 Edit this page → add the next free # row.

 One line for the ask; Area = Flow / Ops / Landing / Babylon / Soundcheck / Process.

 Mark Status when shipped or declined.
