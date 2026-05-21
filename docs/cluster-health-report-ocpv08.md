# StarGate Cluster Health Report — ocpv08

**Cluster**: `ocpv08.dal10.infra.demo.redhat.com`
**Scanned**: 2026-05-06
**Type**: CNV lab workload cluster (large)
**Nodes**: 25 (3 control plane, 14 compute/worker, 1 unknown-metrics, 7 ceph)

## Lab Health Summary

| Metric | Value |
|---|---|
| Total sandbox namespaces | 578 |
| Namespaces with running pods | 514 |
| Namespaces with issues | 13 |
| **Lab health rate** | **97.4%** |

## Lab Failures (13 namespaces)

### Actively Provisioning (7 — likely transient)

| Namespace | Pod | Status |
|---|---|---|
| `sandbox-8mhcx-ocp4-cluster` | virt-launcher-control-plane | ContainerCreating |
| `sandbox-c892s-zt-ansiblebu` | virt-launcher-rhel-1 | ContainerCreating |
| `sandbox-dzhj7-zt-rhelbu` | showroom | PodInitializing |
| `sandbox-gjnp5-1-zt-ansiblebu` | showroom | Init:2/3 |
| `sandbox-hmsl9-zt-ansiblebu` | showroom | Init:2/3 |
| `sandbox-j6f2w-zt-rhelbu` | virt-launcher-rhel | ContainerCreating |
| `sandbox-t7g9b-ocp4-cluster` | virt-launcher-compute01 | ContainerCreating |
| `sandbox-tsgxq-zt-rhelbu` | showroom | Init:0/3 |
| `sandbox-x7vrr-zt-rhelbu` | showroom | Init:2/3 |

### Broken Labs (2 — real failures)

| Namespace | Pod | Status | Duration |
|---|---|---|---|
| `sandbox-lghz8-zt-ansiblebu` | showroom | Init:CrashLoopBackOff | — |
| `sandbox-sj2jh-zt-ansiblebu` | showroom | Init:CrashLoopBackOff | — |

**Classification**: `showroom_init_crashloop`
**Impact**: Two users' lab environments are unusable — showroom UI won't start.

## Cluster Resource Pressure

### Hot Nodes (CPU > 80%)

| Node | CPU | Memory | Role |
|---|---|---|---|
| `ocp-virt8-host3` | **84%** | 52% | compute |
| `ocp-virt8-host4` | **88%** | 53% | compute |
| `ocp-virt8-host5` | **82%** | 49% | compute |
| `ocp-virt8-host6` | **88%** | 36% | compute |

4 of 14 compute nodes above 80% CPU. The cluster is under significant compute pressure. Several other nodes are in the 65-78% range. This is a capacity risk for Summit if more labs are provisioned.

### Unknown Metrics Node

`ocp-virt8-host` reports `<unknown>` for CPU and memory metrics despite being `Ready`. Node is functioning but metrics collection is broken — kubelet is healthy but metrics-server can't scrape it. MetalLB speaker is crashlooping on this node (see below).

## Platform Issues

### HIGH: MetalLB speaker CrashLoopBackOff on 2 nodes (14 days)
- **Namespace**: `metallb-system`
- **Nodes affected**: `ocp-virt8-host` and `ocp-virt8-host3`
- **Classification**: `network_operator_crashloop`
- **Detail**: MetalLB speaker pods crashing every ~3 minutes for 14 days. 394 and 369 restarts respectively. Logs show clean shutdown cycle — the speaker starts, joins memberlist, then receives shutdown signal immediately.
- **Impact**: Load balancer IP assignment may be unreliable on these nodes. Could affect lab service accessibility.
- **Remediation**: Check if MetalLB version is compatible with OCP version. Check FRR configuration for errors.

### CRITICAL: Ceph cleanup failures (1,349 Error pods)
- Same pattern as ocpv06. Ceph storage cleanup jobs failing. Storage reclamation not happening.

### CRITICAL: ccm-monitoring push failing (8 Error pods)
- Same pattern as ocpv06 and infra01. Monitoring push to Icinga failing.

### SYSTEMIC: kubernetes-secret-generator
- Running but with **37,078 restarts over 136 days**. Different behavior than other clusters (Running vs CrashLoopBackOff), but still crashing and restarting constantly.

## Cross-Cluster Patterns Updated

| Issue | ocpv06 | ocpv08 | infra01 | infra02 |
|---|---|---|---|---|
| ccm-monitoring push failing | Yes | Yes | Yes | — |
| Ceph cleanup errors | 1,509 pods | 1,349 pods | — | — |
| kubernetes-secret-generator | CrashLoop 22d | 37,078 restarts 136d | CrashLoop 22d | CrashLoop 22d |
| MetalLB speaker crash | — | 2 nodes, 14d | — | — |
| Showroom CrashLoopBackOff | 1 lab | 2 labs | — | — |
| Hot nodes (>80% CPU) | — | 4 nodes | — | — |
