# All Failures — Last 12 Hours

**Window**: 2026-05-06 ~11:00-23:00 UTC

## Failure Summary by Type

| Failure Type | ocpv05 | ocpv06 | ocpv07 | ocpv08 | ocpv09 | ocpv10 | infra01 | us-east-1 | Total |
|---|---|---|---|---|---|---|---|---|---|
| Ceph cleanup Error | 36 | 60 | 46 | 37 | 157 | 1,045 | — | — | **1,381** |
| CCM monitoring push | 3 | 8 | 3 | 3 | 3 | 3 | 3 | — | **26** |
| Sandbox backup Error | — | — | — | — | — | — | 6 | — | **6** |
| Babylon backup Error | — | — | — | — | — | — | — | 4 | **4** |
| Labagator build Error | — | — | — | — | — | — | 10 | — | **10** |
| Sandbox VM Pending | — | — | 1 | — | — | — | — | — | **1** |
| **Total** | **39** | **68** | **50** | **40** | **160** | **1,048** | **19** | **4** | **1,428** |

## Non-Platform Failures (last 12h)

### ocpv07 — 1 failure

| Namespace | Pod | Status | Age |
|---|---|---|---|
| sandbox-844sv-ocp4-cluster | virt-launcher-control-plane-cluster-844sv-3 | **Pending** | 80min |

Root cause: Cannot schedule — insufficient CPU on target node.

### ocpv-infra01 — 16 failures

**Sandbox backups** (6 pods):
- `sandbox-cluster-backup` Error every hour — SSH key broken (`error in libcrypto`)
- 3 consecutive hourly failures (40min, 100min, 160min ago)

**Labagator frontend builds** (10 pods):
- 5 failures in `labagator-dev`, 5 in `labagator-prod`
- All 9-10 hours old — CRI-O container logs unrecoverable
- Later builds succeeded (3h ago) — transient issue, recovered

### ocp-us-east-1 — 4 failures

**Babylon cross-cluster backup** Error:
- 4 pods failed in last 40 minutes
- Root cause: `no space left on device` — backup PVC is full
- Backup attempts every 30min, all failing

## Warning Events — Last 12 Hours

### PVC/DataVolume ISO Issues (all clusters)

| Cluster | installation-iso warnings | scale-iso warnings |
|---|---|---|
| ocpv10 | 72 PVC + 69 DV = **141** | 21 PVC + 20 DV = 41 |
| ocpv08 | 36 PVC + 26 DV = **62** | — |
| ocpv06 | 23 PVC + 20 DV = **43** | 13 PVC + 10 DV = 23 |
| ocpv07 | 14 PVC + 13 DV = **27** | — |

**`installation-iso`** and **`scale-iso`** PVCs/DataVolumes are producing warnings across all clusters. These are the ISO images used to bootstrap nested OCP cluster VMs. The warnings indicate provisioning delays or failures for these images.

### Control-Plane VM Probe Failures

Every cluster has 5-7 warning events per control-plane VM pod. These are readiness/liveness probe timeouts on the nested OCP API servers — the same CPU pressure issue causing the probes to time out.

| Cluster | Unique control-plane pods with warnings |
|---|---|
| ocpv07 | 15+ |
| ocpv08 | 14+ |
| ocpv10 | 10+ |
| ocpv06 | 6+ |

### DNS Probe Failures

| Cluster | DNS Pod | Node | Node CPU | Events |
|---|---|---|---|---|
| ocpv06 | dns-default-7gm4q | ocp-virt6-host7 | **98%** | Liveness timeout 14min ago |
| ocpv06 | dns-default-cvcvx | ocp-virt6-host6 | **90%** | Liveness + Readiness 83min ago |
| ocpv06 | dns-default-dp9xd | ocp-virt6-host5 | **97%** | Liveness + Readiness 33min ago |
| ocpv07 | dns-default-zvr74 | ocp-virt7-host8 | 77% | Readiness 132min + Liveness 56min ago |
| ocpv08 | dns-default-nhgkc | ocp-virt8-host13 | 46% | Readiness 61min ago |

### CNV Image Prep Failures (ocpv07)

cnv-images namespace producing `exceeded` and `CANCEL` warnings for image prep pods. Base VM images failing to prepare — affects ability to provision new labs.

### Windows VM Warnings (ocpv06)

12 warning events for `virtualmachineinstance/windows` — Windows VMs producing health check warnings.

## Ceph Cleanup — 12-Hour Breakdown

| Cluster | Error Pods (12h) | Rate |
|---|---|---|
| ocpv10 | **1,045** | ~87/hour |
| ocpv09 | 157 | ~13/hour |
| ocpv06 | 60 | ~5/hour |
| ocpv07 | 46 | ~4/hour |
| ocpv08 | 37 | ~3/hour |
| ocpv05 | 36 | ~3/hour |
| **Total** | **1,381** | **~115/hour** |

ocpv10 is generating 87 failed Ceph cleanup pods per hour — far worse than any other cluster. Storage reclamation is completely broken there.

## Top CPU Consumers Right Now

### ocpv06 — DNS-affecting nodes

| Pod | CPU | Type |
|---|---|---|
| prometheus-k8s-1 | **13,425m** | Platform monitoring |
| prometheus-k8s-0 | **10,930m** | Platform monitoring |
| control-plane-cluster-9hmq2-1 | 9,591m | Nested OCP |
| worker-cluster-8xvwn-3 | 8,683m | Nested OCP |
| worker-cluster-cn9rj-3 | 8,237m | Nested OCP |
| splunk-clf | 7,996m | Platform logging |
| control-plane-cluster-5hf8r-1 | 7,618m | Nested OCP |
| control-plane-cluster-qtl9h-1 | 7,587m | Nested OCP |
| control-plane-cluster-6xmlj-2 | 7,512m | Nested OCP |
| control-plane-cluster-bz8nl-3 | 7,429m | Nested OCP |

Prometheus alone: **24,355m (24 CPU cores)** on ocpv06.

### ocpv07 — Scheduling failures

| Pod | CPU | Type |
|---|---|---|
| control-plane-cluster-jk8sm-2 | **10,309m** | Nested OCP |
| control-plane-cluster-pnnlb-1 | 10,184m | Nested OCP |
| control-plane-cluster-98zfv-1 | 9,995m | Nested OCP |
| control-plane-cluster-6b2sf-2 | 8,753m | Nested OCP |
| control-plane-cluster-jvgrt-1 | 8,189m | Nested OCP |
| control-plane-cluster-rdhcw-1 | 7,350m | Nested OCP |
| control-plane-cluster-vzsr7-2 | 7,012m | Nested OCP |
| control-plane-cluster-2vmjg-1 | 6,854m | Nested OCP |
| prometheus-k8s-0 | 6,571m | Platform monitoring |
| control-plane-cluster-mn788-1 | 6,563m | Nested OCP |

**8 of top 10 are nested OCP control planes.** Each consuming 6,500-10,300m.

### ocpv08

| Pod | CPU | Type |
|---|---|---|
| control-plane-cluster-fgm9t-1 | **12,442m** | Nested OCP |
| control-plane-cluster-dlspr-2 | 10,252m | Nested OCP |
| control-plane-cluster-bmjxf-1 | 9,900m | Nested OCP |
| worker-cluster-hnkwt-2 | 9,144m | Nested OCP |
| control-plane-cluster-dlspr-3 | 8,936m | Nested OCP |
| control-plane-cluster-2j4g9-3 | 8,847m | Nested OCP |
| control-plane-cluster-zhz5m-1 | 8,532m | Nested OCP |
| splunk-clf | 8,107m | Platform logging |
| control-plane-cluster-8mhcx-2 | 8,054m | Nested OCP |
| control-plane-cluster-nzzsr-1 | 8,001m | Nested OCP |

### ocpv10

| Pod | CPU | Type |
|---|---|---|
| bastion (sandbox-6hwmz) | **19,226m** | Nested OCP bastion |
| bastion (sandbox-p9wkf) | **13,508m** | Nested OCP bastion |
| control-plane-cluster-4bwk9-3 | 10,561m | Nested OCP |
| control-plane-cluster-crhmb-1 | 10,261m | Nested OCP |
| control-plane-cluster-cqvzn-3 | 10,122m | Nested OCP |
| control-plane-cluster-kx6mf-2 | 9,759m | Nested OCP |
| worker-cluster-lp9nd-5 | 8,503m | Nested OCP |
| control-plane-cluster-pgk2w-1 | 8,262m | Nested OCP |
| worker-cluster-lp9nd-8 | 8,172m | Nested OCP |
| worker-cluster-lp9nd-6 | 8,130m | Nested OCP |

**Two bastion VMs consuming 32,734m (33 CPU cores) combined.** One lab (`sandbox-lp9nd`) has 3 workers in the top 10 consuming 24,805m alone.

## The 12-Hour Cascade

```
509 ocp4-cluster labs provisioned (12h)
  → Each lab: 3 control-plane VMs × 6-11 cores + workers × 6-9 cores
    → Nodes saturate to 77-100% CPU
      → DNS pods fail liveness probes (ocpv06: 3 nodes, ocpv07: 1, ocpv08: 1)
        → Intermittent DNS resolution failures for all pods on those nodes
      → New VM scheduling delays (ocpv07: 1 Pending 80min)
      → Control-plane VM readiness probes timeout (45+ warnings across 4 clusters)
        → Nested OCP clusters report degraded health
      → installation-iso PVC warnings (273 events across 4 clusters)
        → New cluster provisioning slowed by ISO download contention
```

Plus platform overhead per cluster:
- Prometheus: 13-24 CPU cores
- Splunk log forwarder: 7-10 CPU cores
- OLM operator: 7 CPU cores

No capacity gate prevented any of this.
