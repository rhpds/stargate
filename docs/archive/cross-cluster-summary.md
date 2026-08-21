# StarGate Cross-Cluster Health Summary

**Scanned**: 2026-05-06
**Clusters**: 6
**Total namespaces**: 2,572+
**Total sandbox lab environments**: 2,365

## Lab Health by Cluster

| Cluster | Location | Nodes | Sandbox NS | Active Labs | Failures | Health Rate |
|---|---|---|---|---|---|---|
| ocpv01 (dfw3) | Dallas | 50 | 120 | 120 | 0 | **100%** |
| ocpv06 (dal10) | Dallas | 9+ | 1,013 | 517 | 10 | 98.0% |
| ocpv08 (dal10) | Dallas | 25 | 578 | 514 | 13 | 97.4% |
| ocpv10 (wdc07) | Washington DC | 12+ | 654 | 609 | 6 | 99.0% |
| **Total** | | **96+** | **2,365** | **1,760** | **29** | **98.4%** |

## Cluster Resource Pressure

| Cluster | CPU Pressure | Memory Pressure | Risk Level |
|---|---|---|---|
| ocpv01 | 1-6% | 4-8% | Low — significant headroom |
| ocpv06 | Low | Low | Low |
| ocpv08 | 4 nodes >80% | 36-58% | **Medium** — approaching limits |
| ocpv10 | **9 of 9 nodes >75%, one at 99%** | 61-69% | **CRITICAL** — at capacity |
| infra01 | 1-2% | 49-52% | Medium — memory tight for VM scheduling |
| infra02 | 0-5% | 26-37% | Low |

## Platform Issues — Cross-Cluster Patterns

### 1. Ceph Cleanup Failure (ALL lab clusters)

Every lab cluster has failing Ceph storage cleanup jobs. Storage from destroyed lab environments is not being reclaimed.

| Cluster | Error Pods | Severity |
|---|---|---|
| ocpv01 | 2,910 | High |
| ocpv06 | 1,518 | High |
| ocpv08 | 1,350 | High |
| ocpv10 | **10,318** | Critical |
| **Total** | **16,096** | |

**Classification**: `ceph_cleanup_systemic`
**Impact**: Ceph storage filling up across all clusters. Will eventually cause provisioning failures when disk space runs out.
**Root cause**: Cleanup jobs error when processing RBD images from destroyed sandboxes. Needs investigation of Ceph cluster health and cleanup script.

### 2. CCM Monitoring Push Failure (ALL clusters)

Every cluster's monitoring push to Icinga is failing. No cluster is reporting health data to the central monitoring system.

| Cluster | Error Pods | Status |
|---|---|---|
| ocpv01 | 8 | Error |
| ocpv06 | 498 (accumulating) | Error + Pending |
| ocpv08 | 8 | Error |
| ocpv10 | 8 | Error |
| infra01 | 8 | Error (401 Unauthorized) |

**Classification**: `monitoring_push_systemic`
**Impact**: Icinga has no fresh data from any cluster. All monitoring alerts are blind. This is the most dangerous finding — the entire monitoring pipeline is down.

### 3. kubernetes-secret-generator (4 of 6 clusters)

| Cluster | Status | Duration | Restarts |
|---|---|---|---|
| ocpv01 | **Running** (healthy) | — | — |
| ocpv06 | CrashLoopBackOff | 22 days | — |
| ocpv08 | Running (unstable) | 136 days | 37,078 |
| ocpv10 | CrashLoopBackOff | 63 days | 32,449 |
| infra01 | CrashLoopBackOff | 22 days | 11,621 |
| infra02 | CrashLoopBackOff | 22 days | 11,625 |

### 4. CNV Image Import Issues (3 of 4 lab clusters)

| Cluster | Issue |
|---|---|
| ocpv01 | 3 unhealthy |
| ocpv06 | 4 unhealthy (CrashLoopBackOff 2d+) |
| ocpv08 | 1 unhealthy |

Base VM image imports failing. Affects ability to provision new labs.

### 5. Showroom Init CrashLoopBackOff (3 clusters)

| Cluster | Affected Labs |
|---|---|
| ocpv06 | 1 (`sandbox-vvdmj`) |
| ocpv08 | 2 (`sandbox-lghz8`, `sandbox-sj2jh`) |
| ocpv10 | 3 (`sandbox-8xfxg`, `sandbox-fzhbm-1`, `sandbox-l7mmc`) |

6 users across 3 clusters have broken lab environments where the showroom UI won't start. These have been down for days with no alert.

## Infrastructure Cluster Issues (infra01 only)

These findings are specific to the ops tooling cluster and are detailed in the infra01 report:

- CRITICAL: Sandbox backups failing (SSH key broken)
- HIGH: Cost monitor down 56 days
- HIGH: OCP portal auth broken 38 days
- HIGH: 3 VMs can't schedule (insufficient memory)

## Summary

| Finding | Scope | Severity |
|---|---|---|
| Monitoring push failing | **All clusters** | CRITICAL — flying blind |
| Ceph cleanup failing | All lab clusters (16,096 error pods) | CRITICAL — storage risk |
| ocpv10 at CPU capacity | 9 of 9 nodes >75% | CRITICAL — can't add more labs |
| Showroom CrashLoopBackOff | 6 labs across 3 clusters | HIGH — users affected |
| kubernetes-secret-generator | 4 of 6 clusters | HIGH — secret rotation broken |
| CNV image imports | 3 of 4 lab clusters | MEDIUM — affects new provisioning |
| Sandbox backups failing | infra01 | CRITICAL — data loss risk |
| ocpv08 CPU pressure | 4 of 14 nodes >80% | MEDIUM — approaching limits |

**The most urgent finding**: The monitoring system is down across the entire platform. No cluster is reporting health data to Icinga. Every other issue on this list is invisible to ops because the system that should alert on them isn't receiving data. This is exactly the kind of silent, multi-system failure that StarGate is designed to detect — it doesn't depend on the monitoring infrastructure to report its own outage.
