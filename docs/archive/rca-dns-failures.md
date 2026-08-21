# Root Cause Analysis — DNS Probe Failures

**Time**: 2026-05-07 00:09 UTC
**Cluster**: cluster.example.com
**Status**: Active — DNS probes failing right now

## Symptom

CoreDNS pods failing liveness and readiness probes on 3 nodes. When a DNS pod fails readiness, it's removed from the service endpoints. Pods on that node lose DNS resolution until the probe recovers. This causes intermittent DNS failures across the platform.

## Root Cause Chain

### 1. DNS pods failing

| DNS Pod | Node | Last Failure | Probe Type |
|---|---|---|---|
| dns-default-7gm4q | ocp-virt6-host7 | 70min ago | Liveness |
| dns-default-cvcvx | ocp-virt6-host6 | 139min ago | Liveness + Readiness |
| dns-default-dp9xd | ocp-virt6-host5 | 89min ago | Liveness + Readiness |

Error: `Get "http://10.x.x.x:8080/health": context deadline exceeded (Client.Timeout exceeded while awaiting headers)`

The DNS pod is running but **too slow to respond to health checks** because the node's CPU is saturated.

### 2. Nodes are saturated

| Node | CPU | Memory | Total Pods | VMs |
|---|---|---|---|---|
| ocp-virt6-host5 | — | — | 171 | **121 VMs** |
| ocp-virt6-host6 | **164,348m (93%)** | 1,939 GiB (48%) | 202 | **149 VMs** |
| ocp-virt6-host7 | **170,514m (96%)** | 2,092 GiB (52%) | 157 | **102 VMs** |

**ocp-virt6-host6 has 149 VMs running on a single node.**
**ocp-virt6-host7 is at 96% CPU with 102 VMs.**

### 3. What's consuming the CPU

Every VM is a nested OCP control-plane or worker from ocp4-cluster labs. Top consumers per node:

**ocp-virt6-host6** (93% CPU, 149 VMs):

| Pod | CPU | Memory | Lab |
|---|---|---|---|
| control-plane-cluster-9hmq2-1 | **9,176m** | 129 GiB | sandbox-9hmq2 |
| control-plane-cluster-d9lfp-2 | 7,206m | 65 GiB | sandbox-d9lfp |
| worker-cluster-8xvwn-2 | 5,832m | 45 GiB | sandbox-8xvwn |
| control-plane-cluster-bqnst-2 | 5,557m | 31 GiB | sandbox-bqnst |
| control-plane-cluster-52x8q-1 | 5,405m | 55 GiB | sandbox-52x8q |

Top 5 VMs alone: **33,176m (33 CPU cores)** on one node.

**ocp-virt6-host7** (96% CPU, 102 VMs):

| Pod | CPU | Memory | Lab |
|---|---|---|---|
| control-plane-cluster-wx5kr-1 | 6,415m | 64 GiB | sandbox-wx5kr |
| control-plane-cluster-d9lfp-1 | 6,183m | 64 GiB | sandbox-d9lfp |
| control-plane-cluster-dxhmc-3 | 5,196m | 65 GiB | sandbox-dxhmc |
| control-plane-cluster-tbnhp-2 | 5,030m | 65 GiB | sandbox-tbnhp |
| control-plane-cluster-bc4vz-3 | 4,875m | 65 GiB | sandbox-bc4vz |

Top 5 VMs alone: **27,699m (28 CPU cores)** on one node.

**ocp-virt6-host5** (171 pods, 121 VMs):

| Pod | CPU | Memory | Lab |
|---|---|---|---|
| control-plane-cluster-bqnkq-3 | 6,996m | 32 GiB | sandbox-bqnkq |
| control-plane-cluster-bqnst-1 | 5,387m | 25 GiB | sandbox-bqnst |
| control-plane-cluster-lzl6l-2 | 5,009m | 32 GiB | sandbox-lzl6l |
| control-plane-cluster-dxhmc-2 | 4,970m | 64 GiB | sandbox-dxhmc |
| worker-cluster-wbjft-2 | 4,802m | 49 GiB | sandbox-wbjft |

Top 5 VMs alone: **27,164m (27 CPU cores)** on one node.

### 4. Why are there so many VMs per node?

ocpv06 has **158 concurrent ocp4-cluster labs** running right now, producing **825 VMs** across **15 compute nodes**. That's **55 VMs per node average**, but some nodes have up to **149 VMs**.

Each ocp4-cluster lab creates ~5 VMs (3 control-plane + workers). Each control-plane VM consumes 4,000-9,000 millicores. There is no limit on how many labs can be provisioned concurrently on this cluster.

### 5. Why is there no limit?

No provisioning concurrency gate exists. The Sandbox API places labs on clusters via the cluster-scheduler, but there is no check for:
- Current CPU utilization
- Current VM count per node
- Whether DNS pods are healthy
- Whether existing labs are degraded

Labs are placed until the cluster breaks.

## The Causal Chain

```
No provisioning concurrency limit
  → 158 ocp4-cluster labs run simultaneously on 15 nodes
    → 825 VMs (55/node avg, up to 149/node)
      → Nodes at 93-96% CPU
        → CoreDNS pods can't respond to probes within timeout
          → DNS pods fail readiness check
            → DNS pods removed from service endpoints
              → All pods on that node lose DNS resolution
                → Intermittent DNS failures for labs
```

## Proof

**ocpv09** runs 248 concurrent ocp4-cluster labs (more than ocpv06) with **zero DNS failures, zero hot nodes, 30% average CPU**. The difference: ocpv09 has **40 compute nodes** instead of 15. That gives it 24.5 VMs/node instead of 55.

The threshold for DNS stability is **~30 VMs per compute node**. Every 15-node cluster is above this.

## Fix

**Immediate**: Stop new ocp4-cluster provisioning on ocpv06 until VM count drops below 450 (30/node × 15 nodes).

**Short-term**: Implement a concurrency cap — max 90 ocp4-cluster labs per 15-node cluster (30 VMs/node × 15 nodes ÷ 5 VMs/lab).

**Long-term**: CPU-based admission gate that checks cluster-scheduler health score before placing a new lab. This is StarGate's `cluster-health` rubric.
