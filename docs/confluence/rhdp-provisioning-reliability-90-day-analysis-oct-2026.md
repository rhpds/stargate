# RHDP Provisioning Reliability — 90-Day Analysis (Oct 2026)
# Confluence ID: 511804406
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/511804406

Billy Bethell, RHDP Ops — Oct 28, 2026. Data: reporting-db-prod, Jul 28 – Oct 28, 2026. Interpretation updated following feedback from Yordan Yordanov.
 Analysis limitation (flagged by Yordan): Provision counts are from reporting-db-prod only. Interpreting why the EVENT numbers look the way they do — particularly for the Oct 15 AI outage period and the 1–3 week near-full cluster window — requires cross-referencing agd-v2 logs and infrastructure state data from those dates. EVENT section conclusions should be treated as provisional until that context is available.
 At a glance
 Environment
 Provisions
 Failures
 Rate

 PROD — Internal
 103,415
 10,715
 10.4% 
 Healthy baseline, recovering from Sep–Oct incident

 PROD — Partner
 4,640
 781
 16.8% 
 Elevated — not in standard biweekly report

 EVENT
 25,608
 17,378
 67.9% 
 Summit infra, not user-facing labs — see below

 DEV — Internal
 13,539
 4,284
 31.6%
 Expected

 TEST
 573
 174
 30.4%
 Low volume, expected

 CNV this week: 6.9% — recovering from peak of 19.9% on Sep 28. Account bloat fixed Oct 14 (RHDPOPS-24554). SSO/JSON defensive fix (AI#8, agd-v2#227) still needs to land in prod.
 What the numbers say
 PROD Internal is recovering. The Sep–Oct CNV spikes were incident-driven — account bloat fixed Oct 14, SSO crash fix in flight — not a trend. CNV is back to 6.9% this week, down from a peak of 19.9% in late September.
 Partner at 16.8% is the more immediate concern — it wasn't in the previous report at all. Several partner labs are in the 50–90% failure range, mostly CNV-based, and nobody's been watching them. The worst is the Red Hat OpenStack Services on OCP Lab at 90.9%, last attempted Oct 22.
 On the Assisted Installer question: there was a real AI outage during a major deployment that the initial analysis underweighted. Whether the remaining cluster pool failure rate is a capacity issue or something else is still an open question — Yordan is the right person to determine that. Separately, the SSO/JSON defensive fix (AI#8, agd-v2#227) needs to land in prod to stop external transients from crashing provisions outright.
 EVENT environment — what these numbers are
 All near-100% items are EVENT-environment machines — cluster pool managers and tenant deployers pre-provisioning OCP clusters for summit/conference content in development. Not user-ordered labs.
 Two distinct failure types: 
 *-cluster items fail when the shared event cluster runs out of capacity

 *-tenant items are per-lab placement deployers — each fails independently when its own sandbox pool has no available slots. LB2863 and LB2596 are separate labs with separate sandbox pools; they are not downstream from the RAG pool

 Item
 Provisions
 Failures
 Rate
 Notes

 agd-v2.ocp-virt-labs-pool.event — LB1758 RAG Cluster CI
 10,414
 10,204
 98.0%
 Root cluster pool

 summit-2026.lb2645-agentic-devops-cluster.event 
 1,025
 1,017
 99.2%
 Agentic DevOps cluster pool

 agd-v2.ocp-cluster-cnv-pools.event — LB2645 CNV
 3,791
 2,778
 73.3%
 CNV pool

 Tenant deployers (LB1758, LB2645, LB2863, LB2596, LB2391)
 ~1,400
 ~1,260
 ~90%
 Each fails when its own sandbox pool is exhausted — independent failures

 agd-v2.agentops-intel.event — AgentOps on Intel
 1,478
 61
 4.1%
 Working fine — different infrastructure path

 Capacity constraint — not a one-off. When a cluster is full, TenantClusterPool keeps creating ResourceClaims — by-design behaviour that inflates counts. This was a sustained 1–3 week period with near-full clusters, including at least one week where all clusters were disabled except ocpv01. Needs to be planned around for future events.
 There was a real Assisted Installer outage around Oct 15. Its scope needs to be broken out separately so it doesn't get folded into the capacity picture. Slack/PM thread to be reviewed for timeline and scope.
 PROD Internal — elevated items
 10.4% is close to the Jul–Aug baseline of 9–11%. Items that aren't recovering with the rest of CNV:
 Item
 Provisions
 Failures
 Rate
 Platform
 Escalation

 OCP Virt Migration Factory Demo
 226
 120
 53.1%
 CNV
 GPTEINFRA-18383

 Operations and Automation with OCP Virt
 417
 220
 52.8%
 CNV
 —

 OCP Virt Backup/Restore with Veeam Kasten K10
 145
 73
 50.3%
 CNV pool
 —

 Agentic AI with Llama Stack
 112
 51
 45.5%
 CNV (agd-v2)
 —

 llm-d: Scalable LLM Inference
 626
 261
 41.7%
 CNV sandbox
 —

 Azure with ARO Open Environment
 255
 99
 38.8%
 Azure
 —

 Automated Satellite Workshop
 368
 116
 31.5%
 AWS (CI disabled Sep)
 GPTEINFRA-18384

 Experience OCP Virt Roadshow 2026
 1,556
 359
 23.1%
 CNV
 —

 Items at the top — Migration Factory Demo, Virt Automation, Veeam Kasten, llm-d — don't track with the Oct 14 account-bloat fix. Each needs a direct provision attempt with logs.
 Partner catalog — elevated and unwatched
 Partner at 16.8% overall — 60% higher than internal PROD. Almost everything in the top half is CNV-based. None of these appear in the standard biweekly report.
 Partner item
 Provisions
 Failures
 Rate
 Last attempt

 RH OpenStack Services on OCP Lab
 99
 90
 90.9%
 Oct 22

 RH Advanced Developer Suite Demo
 21
 13
 61.9%
 Oct 19

 OCP Virt Migration Factory Demo
 172
 97
 56.4%
 Oct 28

 RHEL In-Place Upgrade Automation Lab
 38
 21
 55.3%
 Oct 24

 Event-Driven Ansible with OCP Demo
 34
 18
 52.9%
 Sep 16

 RHACS Demo (CNV)
 36
 19
 52.8%
 Oct 26

 Product Enablement: RHADS TL3
 38
 20
 52.6%
 Oct 27

 Backup and Recovery with Trilio (OCP Virt)
 52
 21
 40.4%
 Oct 26

 Ansible Product Demos (CNV)
 67
 27
 40.3%
 Oct 25

 Parasol Insurance AI Lab
 77
 20
 26.0%
 Oct 27

 OCP Getting Started Workshop
 209
 39
 18.7%
 Oct 27

 OCP AI: Insurance Claims Demo
 113
 19
 16.8%
 Oct 27

 OCP Multi Workshop (partner CNV)
 955
 102
 10.7%
 Oct 28

 OSP on OCP Lab at 90.9% stands out — the internal version is at 31%. Something is specifically broken on the partner channel: CNV pool access, a credential, or a config mismatch. Hasn't provisioned since Oct 22.
 Assisted Installer — internal vs external
 The split isn't clean yet. There was a real AI outage (~Oct 15) during a major deployment — the initial analysis underweighted this. For the EVENT cluster pools, the high failure rate reflects capacity exhaustion rather than misconfiguration. That's the starting point for investigation, not the conclusion.
 agd-v2.agentops-intel.event ran 1,478 provisions at 4.1% in the same environment, suggesting the AI service itself isn't uniformly down — failures are pool-specific, consistent with capacity or configuration gap.
 On external dependencies: on Oct 21 sso.redhat.com and api.openshift.com returned 5xx and the AI integration crashed because response.json() was called without checking the response type. AI#8 and agd-v2#227 add defensive handling and retry — neither is in prod yet.
 Content owner escalations
 GPTEINFRA-18383 — OCP Virt Migration Factory Demo (53% internal, 56% partner) — raised Oct 28. No prior open escalation existed.

 GPTEINFRA-18384 — Automated Satellite Workshop (31.5%, CI disabled since Sep) — raised Oct 28. Two prior fix attempts (RHDPOPS-23677, RHDPOPS-24535) both closed without full resolution.

 Actions
 Priority
 Item
 Action

 P1
 EVENT cluster pools (LB1758, LB2645, LB2391, LB2863)
 Yordan to assess — capacity vs config. Tenant deployer failures are separate: each fails when its own sandbox pool is exhausted.

 P1
 Partner: OSP on OCP Lab (90.9%)
 Direct investigation — internal version at 31%, so partner-specific gap. Likely CNV pool access or credential.

 P1
 SSO/JSON defensive fix (AI#8, agd-v2#227)
 Merge and deploy. Already written and reviewed.

 P2
 OCP Virt Migration Factory Demo (53% / 56%)
 Direct provision with logs. Failing equally on both channels. (GPTEINFRA-18383)

 P2
 Automated Satellite Workshop (31.5%, AWS)
 AWS-based, not CNV. CI disabled since Sep. (GPTEINFRA-18384)

 P3
 Partner catalog monitoring
 Partner at 16.8% is invisible in the standard biweekly report. Add partner breakdown going forward.

 Next steps
 Pull Slack/PM thread for Oct 15 AI outage — scope needs to be broken out separately from capacity failures

 Cross-reference agd-v2 logs and infra state data for the Oct 15 outage and near-full cluster periods to validate EVENT interpretation

 Identify content owners for GPTEINFRA-18383 and GPTEINFRA-18384

 Technical P1s and broader context: GPTEINFRA-18382

 Reliability report discussion: RHDPOPS-24629
