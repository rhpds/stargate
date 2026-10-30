# Infrastructure - Pain Points
# Confluence ID: 503154034
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/503154034

Purpose
 This page records the constraints and expectations dumped on Infra for OCP-Virt: the day-to-day cost of being the default owner when anything nested, CNV-related, or "in prod" fails.
 Constraints
 Budget
 Budget constrains platform choices before technical preference does:
 Which providers and sites we can use

 Maximum practical node sizes (CPU / memory / local disk)

 Which hardware generations and configurations we can accept

 How many OCP-Virt clusters we can operate and how much storage/network headroom we can fund for peak demand (Summit, RH1, large events)

 How aggressively we can oversubscribe vs. buy real capacity for nested CNV + external ODF workloads

 Time
 Peak/event load must be absorbed by capacity that is already online: we do not scale clusters during the event

 We also cannot permanently oversize for peak without burning budget on idle capacity

 Bare-metal growth has a long critical path (hardware lead time → configuration → install → post-install); demand can sometimes not be met

 Workload-driven feature requests are expected ASAP, with little time for careful rollout

 Always-on availability leaves little calendar for upgrades, scale testing, and reclaim/cleanup work between booking waves

 Infra team
 The Infra team is extremely small and broadly scoped:
 Currently 3 members and 2 individual contributors: no dedicated networking, storage, compute, or automation teams

 The same group covers planning, cluster build/config, AgnosticV, AgnosticD, sandboxes, provisioning paths, troubleshooting, escalations, designing/testing/releasing new features, and project work

 Incidents, event prep, and delivery all pull from the same people

 The team is engaged on nearly every related topic daily, which drives heavy context switching and leaves little uninterrupted time for capacity and hardening work

 Requirements
 These expectations are dropped on Infra and treated as the standard for the Infra team, even though Infra has little room to decide whether they are realistic.
 Nested virtualization 
Infra clusters must support nested virt and offer “high” performance so we have to make some hard choices like for etcd performance we use hostPath+local disks, with the tradeoff that those VMs are not migratable.

 Lab experience and performance 
Nested labs are expected to perform to a high standard regardless of cluster load, networking latency, and similar shared-platform effects.

 Latest product features, ASAP 
This is largely a content/product ask (newer OCP, latest RHEL, AAP2, …), but it still means Infra must be able to support those features on the platform on short notice.

 Operators on nested (and tenant) clusters 
Operators must deploy and work on nested clusters. When they don’t, ownership often lands on Infra: including TenantCluster-related cases, even when the failure is in the workload/operator path.

 External ODF 
Some labs need external ODF so storage can be demonstrated. This adds capacity and operational risk on clusters that are already storage-constrained.

 Fast, reliable provisioning: treated as Infra’s problem 
Deployments are expected to be fast and failure-free. Failures in production items are often escalated to Infra rather than the item developer. We are blind to issues that show up only under high load, concurrent provisions, or when external dependencies throttle or degrade at scale.

 Always-on availability, especially at event scale 
Infrastructure must stay available continuously, including events with thousands of concurrent deployments. Peak load also stresses shared external dependencies (e.g. Assisted Installer / related services), not only the OCP-Virt clusters themselves.

 Cluster reservations without starving everyone else 
Clusters can/should be reservable for events, and that reservation is expected not to harm remaining non-event workloads: i.e. isolation of capacity without a real capacity buffer.

 Cross-cutting expectation 
Infra is expected to engage with the rest of the organization on demand, deliver what’s asked quickly, and often do so without proper testing time, without time to troubleshoot root causes, and without time to apply performance improvements.
 Day-to-day
 Always on call in practice 
Expectation is continuous availability: not only during business hours, and especially around events.

 Tagged with no context 
Infra gets tagged into threads with little or no useful context, then has to fight through endless back-and-forth to extract what is actually broken.

 Noise instead of signal 
“Context” often means AI walls of text or blobs with endless log lines that still lack proper contextualization.

 De facto owners of troubleshooting 
Because Infra is expected to know the full path (catalog → AgnosticD → sandboxes → CNV/ODF → external deps), Infra becomes the default owner of the troubleshooting, not only the infra layer.

 Multiple distinct failures collapsed into one blame 
More often than not, several unrelated issues are presented as a single outage. Infra is the default owner of that combined story, which hides the real split of causes and owners.

 Production without scale or load proof 
Items ship to production without meaningful testing at scale or under high load. The first hard test is live usage; fallout still routes to Infra.
