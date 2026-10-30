# CNV Cluster Ops — Known Issues & Gaps (Oct 2026)
# Confluence ID: 501907733
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/501907733

This is a living document — ops, add your pain here

 If you've had to deal with CNV cluster problems, add a note at the bottom in the Running Log. Date it, sign it, describe what you hit. This doc exists so we can stop rediscovering the same walls every month and start building a real case for investment.

 Clusters in scope: ocpv01–ocpv09 (dal10/dal12), ocpvdev01, ocpvirt3, ocpv-infra01

 Last updated: October 14, 2026

 The short version (for anyone who wasn't on shift Oct 13)

 ocpv06 ran out of memory. ocpv08 had sick nodes. Provisions started failing across the board. We had to manually figure out which cluster was the problem, manually disable items in the catalog, and then sit and watch the queue drain while users were getting failures and opening tickets. There was no alert that told us we were near the edge. There was no plan B. There was no way to tell users "hey, capacity is full" before they clicked Order. They just got a cryptic failure after 45 minutes of waiting.

 This is not a one-time thing. We've been here before. We'll be here again unless something changes.

 1. Capacity saturation — no graceful degradation, no plan B

 What actually happens: A cluster fills up. Provisions start silently degrading — VMIs don't create in time, OLM hangs, assisted installer stalls. We don't know until users start complaining. We dig through Labagator or oc to find the culprit cluster. We manually disable it. We watch the queue drain. We re-enable when it feels safe. We do this by hand every time.

 The missing piece: There is no automatic throttle. No fallback. No pre-order message that says "this type of environment is at capacity right now." The catalog just lets users order into a wall.

 Jira 
 Summary 
 Status 

 RHDPOPS-24544 
 dal10 OCPv prod capacity: ocpv06 memory-saturated, ocpv08 sick nodes 
 Closed 

 RHDPOPS-24547 
 ocpv06 memory ceiling — throttle heavy nested-cluster pools 
 Closed 

 RHDPOPS-24539 
 CNV cluster capacity — incident response and operational hardening 
 Open 

 What we need: 

 Automated admission gate tied to cluster memory headroom — stop accepting work when a cluster is near the ceiling

 A fallback cluster or graceful queue/reject so users get a clear message, not a 45-minute timeout

 Something that pages us before we're already on fire, not after

 2. Flow has no preflight capacity check

 What actually happens: Flow kicks off a deploy onto a cluster that's already full or partially down. The job runs for 30–60 minutes, hits a timeout somewhere deep in OLM or the assisted installer, and fails. The user opens a ticket. We investigate. We find the cluster was full before the job even started. We had the information. We just didn't use it.

 Jira 
 Summary 
 Status 

 RHDPOPS-24319 
 Flow preflight hardening — block deploy when tenant clusters unavailable 
 Open 

 What we need: Flow checks cluster health and headroom before submitting the job. If no healthy cluster is available, it fails fast with a clear reason — not after an hour of provisioning.

 3. Monitoring gaps — we find out from users, not from alerts

 What actually happens: Nodes go NotReady. Nobody knows. Users start getting failures. Someone notices in Slack. We check Icinga. Icinga doesn't have that cluster covered. We add it after the fact. Repeat.

 Jira 
 Summary 
 Status 

 GPTEINFRA-18214 
 ocpv02: enable monitoring and fix missing Icinga alerts for NotReady nodes 
 Open 

 GPTEINFRA-18106 
 Labagator Ops CNV Cluster Overview + Icinga health 
 Closed 

 GPTEINFRA-17568 
 CNV Capacity calculator — Onboard API to infrastructure 
 To Do 

 What we need: 

 Every cluster has Icinga coverage for NotReady nodes, not just the ones we remembered to add

 FleetView's capacity API wired into Flow and the catalog so deploy decisions use live data, not guesswork

 Alerts that fire at 70–75% capacity, giving us time to act before things break

 4. Provision failures under saturation look like software bugs

 What actually happens: A cluster gets busy. Provisions start failing in different ways depending on what was mid-flight when the pressure hit. Some fail with VMI creation timeouts (DataVolume clones slow down massively under concurrent load). Some fail because the assisted installer hangs silently. Some get killed mid-run by an AAP SIGTERM. Every one of these looks like a different bug. The real cause — cluster saturation — is the same.

 This is painful for ops because we end up chasing five different symptom tickets when the fix is "the cluster was full."

 Jira 
 Summary 
 Status 

 RHDPOPS-24543 
 Assisted installer failure analysis under high node saturation 
 Open 

 RHDPOPS-24334 
 Bastion VM stuck 'Provisioning' — KubeVirt VMI never created within 5min timeout 
 Open 

 RHDPOPS-24371 
 ocp-cluster-cnv-pools provision killed by AAP SIGTERM after 69s 
 Open 

 RHDPOPS-24430 
 AAP operator wait timeout on CNV cluster after 2021s 
 Open 

 5. OLM and operator installs time out — stale snapshots make it worse

 What actually happens: Under load, OLM slows down. InstallPlans don't get created. Operators never reach CSV ready state. We hit the timeout and fail. On top of that, our OLM catalog snapshots are pinned to a specific date — if an operator ships a new version and we're running a month-old snapshot, the subscription can't resolve and OLM just sits there spinning.

 Both problems compound each other. Under pressure + stale snapshot = guaranteed failures.

 Jira 
 Summary 
 Status 

 RHDPOPS-24498 
 cert-manager CSV timed out (309s) + OLM/CatalogSource issues on ocpv01 
 Open 

 RHDPOPS-24495 
 OLM failed to create InstallPlan for DevWorkspace Operator (30 retries) 
 Open 

 RHDPOPS-24487 
 OLM catalog snapshot from Aug 31 used Sep 29 — ansible-super-lab 
 Open 

 RHDPOPS-24480 
 OLM snapshot CatalogSource stale, devworkspace-operator never resolved 
 Open 

 RHDPOPS-24493 
 AAP Controller project sync timed out (Gitea under load) 
 Open 

 RHDPOPS-24497 
 HyperConverged operator timeout 1200s on ocpv03 
 Open 

 What we need: Rolling or version-pinned OLM snapshot updates so we're not silently running stale catalogs. Longer-term, OLM timeouts need to be load-aware.

 6. Storage (ODF/Ceph) fills up and we find out too late

 What actually happens: Ceph starts filling. At some threshold it starts refusing writes. Provisions that depend on PVC creation start hanging. Eventually we get a Blocker ticket. We scramble to free space. ocpvdev01 hit this. ocpvirt3 had 24 PVCs stuck Pending for 8 days before anyone caught it. These are not edge cases — Ceph headroom is not something we actively watch, we just wait until something breaks.

 Jira 
 Summary 
 Status 

 RHDPOPS-24130 
 ocpvdev01: Ceph blockpool near-full (Blocker) 
 Closed 

 RHDPOPS-24405 
 ODF StorageCluster never reached ready state — provision failed after 2839s 
 Open 

 GPTEINFRA-17674 
 ocpvirt3: 24 image PVCs stuck Pending in cnv-images for 8 days 
 Closed 

 What we need: Ceph capacity alerts at 70% (not 90%). Automated triage or at least a runbook trigger when ODF StorageCluster fails to reach ready state.

 7. DNS failures on destroy — noisy but invisible

 What actually happens: A cluster-on-CNV gets destroyed. The DNS entry for its API goes away as part of the destroy. Then our destroy job tries to connect to api.cluster-xyz.dyn.redhatworkshops.io and gets NXDOMAIN. The job fails. A ticket gets created. Ops looks at it, confirms the cluster is actually gone, closes the ticket. Repeat, endlessly. It's not causing data loss but it creates a constant stream of false-positive incidents.

 Occasionally this also happens in reverse — a provision job tries to connect to a cluster whose API is not ready yet and gets ECONNREFUSED.

 Jira 
 Summary 
 Status 

 RHDPOPS-24499 
 Destroy job failed — cluster API not DNS-resolvable (already deleted) 
 Open 

 RHDPOPS-24502 
 Cluster API ECONNREFUSED at provision time 
 Open 

 What we need: Destroy jobs that handle DNS failure gracefully — if the API is already gone, that's a success, not a failure. Stop generating tickets for this.

 Summary — what we're missing and why it hurts

 Gap 
 What ops does today 
 What we need 

 Capacity throttling 
 Manually disable cluster per incident 
 Automated gate on memory headroom 

 Plan B when full 
 Nothing — deploys fail into a wall 
 Fallback pool or graceful queue/reject 

 User-facing capacity message 
 None 
 Pre-order check with clear rejection reason 

 Flow preflight 
 No check before submitting job 
 Block deploy if no healthy cluster ( RHDPOPS-24319 ) 

 Node health alerting 
 Inconsistent — gaps per cluster 
 Uniform Icinga + PagerDuty for NotReady 

 Capacity API 
 FleetView exists, not wired in 
 Live data in Flow + catalog ( GPTEINFRA-17568 ) 

 OLM snapshot freshness 
 Date-pinned, goes stale silently 
 Rolling or version-pinned updates 

 Ceph headroom alerting 
 Alert only when already near-full 
 Alert at 70% 

 Destroy-time DNS noise 
 Ticket per failure, ops closes manually 
 Defensive destroy that treats DNS-gone as success 

 Ops running log — add your experience here

 This section is for anyone on the ops team to add notes. Date it, sign it, one paragraph is fine. No judgment, just facts. 

 2026-10-13 — Billy Bethell 
ocpv06 saturated, ocpv08 had sick nodes. Spent the morning manually working out which cluster was the problem, disabling items, watching the queue. No alert fired before we hit the wall — we found out because users started getting failures. No fallback, no way to tell people capacity was tight before they ordered. This needs to be fixed properly, not patched per incident.

 Related pages

 FleetView — CNV Capacity & Cost Planning Tool 

 Fix CNV Paused VMs — Recovery Toolkit 

 How to add Nodes on CNV Cluster 

 Replacing Failed Storage Devices on CNV Infrastructure 

 RHDP Event Ops — Runbook Master Plan
