# StarGate Cluster Health Report — ocpv10

**Cluster**: `ocpv10.wdc07.infra.demo.redhat.com`
**Scanned**: 2026-05-06
**Type**: CNV lab workload cluster

## Lab Health

| Metric | Value |
|---|---|
| Sandbox namespaces | 654 |
| Active with running pods | 609 |
| With issues | 6 |
| **Lab health rate** | **99.0%** |

### Lab Failures

| Namespace | Pod | Status |
|---|---|---|
| `sandbox-4mf69-zt-rhelbu` | showroom | Init:0/3 (provisioning) |
| `sandbox-5w7g5-zt-ansiblebu` | showroom | Init:2/3 (provisioning) |
| `sandbox-8xfxg-zt-ansiblebu` | showroom | **Init:CrashLoopBackOff** |
| `sandbox-fzhbm-1-zt-ansiblebu` | showroom | **Init:CrashLoopBackOff** |
| `sandbox-l7mmc-zt-rhelbu` | showroom | **Init:CrashLoopBackOff** |

3 real failures (showroom CrashLoopBackOff), 2 provisioning.

## CRITICAL: Cluster Under Heavy CPU Pressure

| Node | CPU | Memory |
|---|---|---|
| `ocp-virt10-host3` | **99%** | 67% |
| `ocp-virt10-host6` | **93%** | 65% |
| `ocp-virt10-host4` | **83%** | 64% |
| `ocp-virt10-host2` | **82%** | 64% |
| `ocp-virt10-host` | **81%** | 64% |
| `ocp-virt10-host9` | **81%** | 69% |
| `ocp-virt10-host5` | 77% | 66% |
| `ocp-virt10-host7` | 76% | 61% |
| `ocp-virt10-host8` | 75% | 67% |

**9 of 9 compute nodes above 75% CPU. One node at 99%.** This cluster is at capacity. Memory is also elevated (61-69%). Any additional lab provisioning risks pod scheduling failures or performance degradation for all running labs.

## Platform Issues

| Issue | Count |
|---|---|
| Ceph cleanup Error pods | **10,318** (worst of any cluster) |
| ccm-monitoring push failures | 8 |
| kubernetes-secret-generator | CrashLoopBackOff (63 days, 32,449 restarts) |
| cnv-images | 1 issue |
