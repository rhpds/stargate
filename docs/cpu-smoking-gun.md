# CPU Saturation Root Cause — Smoking Gun

**Date**: 2026-05-06
**Finding**: Nested OpenShift control-plane VMs are the single root cause of CPU saturation, DNS failures, provisioning failures, and scheduling delays across the RHDP platform.

## The Smoking Gun

Every top CPU consumer on every hot cluster is the same thing: `virt-launcher-control-plane-cluster-*` — nested OpenShift control plane VMs provisioned by the `ocp4-cluster` lab type.

### Per-VM CPU Consumption

| VM Type | CPU Cores Per VM | Memory Per VM |
|---|---|---|
| Control plane VM | 6,000-11,000m (6-11 cores) | 32-131 GiB |
| Worker VM | 5,500-9,400m (5.5-9.4 cores) | 49-65 GiB |
| Bastion VM (ocpv10) | **18,408m (18 cores)** | 218-410 GiB |

**One ocp4-cluster lab = 3 control planes + N workers = 25-40 CPU cores consumed.**

### Top CPU Consumers — ocpv06 (100% CPU on host7)

| Namespace | Pod | CPU | Memory |
|---|---|---|---|
| sandbox-9hmq2-ocp4-cluster | control-plane-cluster-9hmq2-1 | **11,246m** | 128 GiB |
| openshift-monitoring | prometheus-k8s-1 | 9,399m | 23 GiB |
| sandbox-8xvwn-ocp4-cluster | worker-cluster-8xvwn-3 | 8,374m | 64 GiB |
| sandbox-7d246-ocp4-cluster | control-plane-cluster-7d246-1 | 8,226m | 32 GiB |
| openshift-monitoring | prometheus-k8s-0 | 8,165m | 22 GiB |
| sandbox-qtl9h-ocp4-cluster | control-plane-cluster-qtl9h-1 | 8,160m | 131 GiB |
| sandbox-5hf8r-ocp4-cluster | control-plane-cluster-5hf8r-1 | 7,755m | 130 GiB |
| sandbox-d9lfp-ocp4-cluster | control-plane-cluster-d9lfp-2 | 7,555m | 64 GiB |
| openshift-operator-lifecycle-manager | olm-operator | 7,294m | 763 MiB |
| sandbox-cn9rj-ocp4-cluster | worker-cluster-cn9rj-1 | 7,166m | 49 GiB |
| openshift-logging | splunk-clf | 6,892m | 17 GiB |

### Top CPU Consumers — ocpv07 (96% CPU on host9)

| Namespace | Pod | CPU | Memory |
|---|---|---|---|
| sandbox-98zfv-ocp4-cluster | control-plane-cluster-98zfv-1 | **10,654m** | 100 GiB |
| sandbox-jk8sm-ocp4-cluster | control-plane-cluster-jk8sm-2 | 10,273m | 61 GiB |
| sandbox-pnnlb-ocp4-cluster | control-plane-cluster-pnnlb-1 | 10,222m | 131 GiB |
| sandbox-6b2sf-ocp4-cluster | control-plane-cluster-6b2sf-2 | 9,004m | 64 GiB |
| sandbox-2vmjg-ocp4-cluster | control-plane-cluster-2vmjg-1 | 7,293m | 131 GiB |
| sandbox-xrc97-ocp4-cluster | control-plane-cluster-xrc97-1 | 6,953m | 130 GiB |

### Top CPU Consumers — ocpv08 (88% CPU on host4)

| Namespace | Pod | CPU | Memory |
|---|---|---|---|
| sandbox-7v75b-ocp4-cluster | control-plane-cluster-7v75b-1 | **10,432m** | 130 GiB |
| sandbox-nzzsr-ocp4-cluster | control-plane-cluster-nzzsr-3 | 9,975m | 32 GiB |
| openshift-logging | splunk-clf | 9,691m | 13 GiB |
| sandbox-hnkwt-ocp4-cluster | worker-cluster-hnkwt-2 | 9,427m | 49 GiB |
| sandbox-wq5pm-ocp4-cluster | control-plane-cluster-wq5pm-1 | 8,740m | 96 GiB |

### Top CPU Consumers — ocpv10 (99% CPU on host3)

| Namespace | Pod | CPU | Memory |
|---|---|---|---|
| sandbox-6hwmz-ocp4-cluster | bastion | **18,408m** | 218 GiB |
| sandbox-p9wkf-ocp4-cluster | bastion | **14,670m** | 410 GiB |
| sandbox-crhmb-ocp4-cluster | control-plane-cluster-crhmb-1 | 11,395m | 131 GiB |
| sandbox-2nkmj-ocp4-cluster | control-plane-cluster-2nkmj-dr-1 | 11,209m | 18 GiB |
| sandbox-2g7z7-ocp4-cluster | control-plane-cluster-2g7z7-3 | 8,398m | 55 GiB |

## Provisioning Volume — Last 7 Days

| Cluster | ocp4-cluster Labs | zt-ansible Labs | zt-rhel Labs | Total |
|---|---|---|---|---|
| **ocpv06** | **622** | 104 | 278 | 1,004 |
| ocpv10 | 203 | 111 | 325 | 639 |
| ocpv07 | 183 | 97 | 217 | 497 |
| ocpv08 | 153 | 111 | 260 | 524 |

622 ocp4-cluster labs on ocpv06 × ~30 CPU cores each = **~18,660 CPU cores requested** on a cluster that doesn't have that capacity.

## Platform Overhead

In addition to the lab VMs, platform services are consuming significant CPU:

| Service | Cluster | CPU |
|---|---|---|
| prometheus-k8s (×2) | ocpv06 | 17,564m (17.5 cores) |
| splunk-clf (log forwarder) | ocpv06 | 6,892m (7 cores) |
| splunk-clf | ocpv08 | 9,691m (10 cores) |
| olm-operator | ocpv06 | 7,294m (7 cores) |

Prometheus and the Splunk log forwarder alone consume 25-35 CPU cores per cluster.

## The Cascade

```
ocp4-cluster labs provisioned without capacity check
  → Nested OCP control-plane VMs consume 6-11 CPU cores each
    → Nodes hit 80-100% CPU
      → DNS pod liveness probes time out
        → DNS pods marked unready, removed from endpoints
          → Labs on those nodes lose DNS resolution
            → Intermittent DNS failures across the platform
      → New VM scheduling delayed (ContainerCreating for hours)
        → Provisioning failures on ocpv07
      → MetalLB speaker probes fail
        → Load balancer IP assignment unreliable
      → VM readiness probes fail
        → Nested OCP control planes marked unhealthy
```

One root cause → five symptoms. The nested OCP cluster VMs are consuming all available CPU, and every other failure (DNS, scheduling, MetalLB, provisioning) is a downstream effect of that saturation.

## What's Missing

Nothing checks whether a cluster has capacity before provisioning another ocp4-cluster lab. The placement decision happens in the Sandbox API / cluster-scheduler, but there is no gate that says "this cluster is at 90% CPU, don't add a 30-core lab." The labs keep getting placed until the cluster breaks.

This is the cluster-health gate in the StarGate plan — `cluster_reachable`, `cpu_usage_acceptable`, `memory_usage_acceptable`, `no_critical_alerts` — evaluated before provisioning. If that gate existed, ocpv06 would have stopped accepting ocp4-cluster labs days ago, and the DNS failures, scheduling delays, and provisioning failures would not have occurred.
