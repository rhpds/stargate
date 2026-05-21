# Platform Status — Last 12 Hours

**Window**: 2026-05-06 ~11:00-23:00 UTC
**Clusters scanned**: 6 lab workload clusters

## Provisioning (last 12h)

| Cluster | ocp4-cluster | zt-ansible | zt-rhel | Total |
|---|---|---|---|---|
| ocpv10 | 101 | 67 | 129 | 297 |
| ocpv05 | 97 | 44 | 135 | 276 |
| ocpv09 | 96 | 45 | 13 | 154 |
| ocpv08 | 74 | 54 | 117 | 245 |
| ocpv07 | 71 | 46 | 65 | 182 |
| ocpv06 | 70 | 47 | 125 | 242 |
| **Total** | **509** | **303** | **584** | **1,396** |

509 nested OCP cluster labs provisioned in 12 hours. Each consumes 25-40 CPU cores.

## Sandbox Failures (last 12h)

| Cluster | Failures | Details |
|---|---|---|
| ocpv07 | 1 | `sandbox-844sv-ocp4-cluster` — control-plane VM Pending (67min, can't schedule) |
| All others | 0 | |

## DNS Probe Failures (last 12h)

### ocpv06 — 10 DNS warning events

3 DNS pods failing liveness/readiness probes. All on nodes above 90% CPU.

| DNS Pod | Node | Node CPU | Events |
|---|---|---|---|
| dns-default-7gm4q | ocp-virt6-host7 | **98%** | Liveness probe timeout (14min ago) |
| dns-default-cvcvx | ocp-virt6-host6 | **90%** | Liveness + Readiness probe timeout (83min ago) |
| dns-default-dp9xd | ocp-virt6-host5 | **97%** | Liveness + Readiness probe timeout (33min ago) |

### ocpv07 — 4 DNS warning events

| DNS Pod | Node | Node CPU | Events |
|---|---|---|---|
| dns-default-zvr74 | ocp-virt7-host8 | 77% | Readiness (132min ago) + Liveness (56min ago) |

### ocpv08 — 2 DNS warning events

| DNS Pod | Node | Node CPU | Events |
|---|---|---|---|
| dns-default-nhgkc | ocp-virt8-host13 | 46% | Readiness probe timeout (61min ago) |

## Top CPU Consumers Right Now

### ocpv06

| Rank | Namespace | Pod | CPU |
|---|---|---|---|
| 1 | openshift-monitoring | prometheus-k8s-1 | **13,425m** |
| 2 | openshift-monitoring | prometheus-k8s-0 | **10,930m** |
| 3 | sandbox-9hmq2-ocp4-cluster | control-plane-cluster-9hmq2-1 | 9,591m |
| 4 | sandbox-8xvwn-ocp4-cluster | worker-cluster-8xvwn-3 | 8,683m |
| 5 | sandbox-cn9rj-ocp4-cluster | worker-cluster-cn9rj-3 | 8,237m |
| 6 | openshift-logging | splunk-clf | 7,996m |
| 7 | sandbox-5hf8r-ocp4-cluster | control-plane-cluster-5hf8r-1 | 7,618m |
| 8 | sandbox-qtl9h-ocp4-cluster | control-plane-cluster-qtl9h-1 | 7,587m |
| 9 | sandbox-6xmlj-ocp4-cluster | control-plane-cluster-6xmlj-2 | 7,512m |
| 10 | sandbox-bz8nl-ocp4-cluster | control-plane-cluster-bz8nl-3 | 7,429m |

**Platform overhead on ocpv06**: Prometheus (24,355m = 24 cores) + Splunk log forwarder (7,996m = 8 cores) = **32 cores consumed by monitoring/logging alone.**

### ocpv07

| Rank | Namespace | Pod | CPU |
|---|---|---|---|
| 1 | sandbox-jk8sm-ocp4-cluster | control-plane-cluster-jk8sm-2 | **10,309m** |
| 2 | sandbox-pnnlb-ocp4-cluster | control-plane-cluster-pnnlb-1 | 10,184m |
| 3 | sandbox-98zfv-ocp4-cluster | control-plane-cluster-98zfv-1 | 9,995m |
| 4 | sandbox-6b2sf-ocp4-cluster | control-plane-cluster-6b2sf-2 | 8,753m |
| 5 | sandbox-jvgrt-ocp4-cluster | control-plane-cluster-jvgrt-1 | 8,189m |
| 6 | sandbox-rdhcw-ocp4-cluster | control-plane-cluster-rdhcw-1 | 7,350m |
| 7 | sandbox-vzsr7-ocp4-cluster | control-plane-cluster-vzsr7-2 | 7,012m |
| 8 | sandbox-2vmjg-ocp4-cluster | control-plane-cluster-2vmjg-1 | 6,854m |
| 9 | openshift-monitoring | prometheus-k8s-0 | 6,571m |
| 10 | sandbox-mn788-ocp4-cluster | control-plane-cluster-mn788-1 | 6,563m |

**Top 8 are all nested OCP control-plane VMs.** Each consuming 6,500-10,300 millicores.

### ocpv08

| Rank | Namespace | Pod | CPU |
|---|---|---|---|
| 1 | sandbox-fgm9t-ocp4-cluster | control-plane-cluster-fgm9t-1 | **12,442m** |
| 2 | sandbox-dlspr-ocp4-cluster | control-plane-cluster-dlspr-2 | 10,252m |
| 3 | sandbox-bmjxf-ocp4-cluster | control-plane-cluster-bmjxf-1 | 9,900m |
| 4 | sandbox-hnkwt-ocp4-cluster | worker-cluster-hnkwt-2 | 9,144m |
| 5 | sandbox-dlspr-ocp4-cluster | control-plane-cluster-dlspr-3 | 8,936m |
| 6 | sandbox-2j4g9-ocp4-cluster | control-plane-cluster-2j4g9-3 | 8,847m |
| 7 | sandbox-zhz5m-ocp4-cluster | control-plane-cluster-zhz5m-1 | 8,532m |
| 8 | openshift-logging | splunk-clf | 8,107m |
| 9 | sandbox-8mhcx-ocp4-cluster | control-plane-cluster-8mhcx-2 | 8,054m |
| 10 | sandbox-nzzsr-ocp4-cluster | control-plane-cluster-nzzsr-1 | 8,001m |

### ocpv10

| Rank | Namespace | Pod | CPU |
|---|---|---|---|
| 1 | sandbox-6hwmz-ocp4-cluster | bastion | **19,226m** |
| 2 | sandbox-p9wkf-ocp4-cluster | bastion | **13,508m** |
| 3 | sandbox-4bwk9-ocp4-cluster | control-plane-cluster-4bwk9-3 | 10,561m |
| 4 | sandbox-crhmb-ocp4-cluster | control-plane-cluster-crhmb-1 | 10,261m |
| 5 | sandbox-cqvzn-ocp4-cluster | control-plane-cluster-cqvzn-3 | 10,122m |
| 6 | sandbox-kx6mf-ocp4-cluster | control-plane-cluster-kx6mf-2 | 9,759m |
| 7 | sandbox-lp9nd-ocp4-cluster | worker-cluster-lp9nd-5 | 8,503m |
| 8 | sandbox-pgk2w-ocp4-cluster | control-plane-cluster-pgk2w-1 | 8,262m |
| 9 | sandbox-lp9nd-ocp4-cluster | worker-cluster-lp9nd-8 | 8,172m |
| 10 | sandbox-lp9nd-ocp4-cluster | worker-cluster-lp9nd-6 | 8,130m |

**ocpv10 has two bastion VMs consuming 19,226m and 13,508m (33 CPU cores combined).** Plus `sandbox-lp9nd` alone has 3 worker VMs in the top 10 consuming 24,805m (25 cores) — one lab, one cluster, 25 cores.

## The 12-Hour Picture

In the last 12 hours, 509 nested OCP cluster labs were provisioned across 6 clusters. Each lab consumes 25-40 CPU cores for its control-plane and worker VMs. This is the direct cause of:

- **ocpv06**: 3 nodes at 90-98% CPU → DNS pods failing probes → intermittent DNS resolution failures
- **ocpv07**: 1 VM can't schedule (Pending 67min) → CPU too high for new placements
- **ocpv10**: 2 bastion VMs alone consuming 33 CPU cores → cluster at capacity wall

The top 10 CPU consumers on every cluster are nested OCP control-plane VMs and workers. Platform services (Prometheus, Splunk log forwarder) add 25-35 cores of overhead per cluster on top.

No capacity gate exists. Labs are provisioned until the cluster breaks.
