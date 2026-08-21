# StarGate Full Platform Scan

**Date**: 2026-05-06
**Clusters scanned**: 10 (2 infra + 8 lab workload)
**Method**: Read-only `oc get` — no modifications made

## Platform Totals

| Metric | Value |
|---|---|
| Total clusters | 10 |
| Total namespaces | 8,693 |
| Total sandbox (lab) namespaces | 4,257 |
| Active labs with running pods | 3,394 |
| Labs with failures | 49 |
| **Platform-wide lab health rate** | **98.6%** |
| Total unhealthy platform pods | 27,929 |
| Total Ceph cleanup errors | 27,298 |
| Showroom CrashLoopBackOff (broken labs) | 13 |
| Nodes with >80% CPU | 25 |

## Per-Cluster Summary

| Cluster | Location | Sandbox NS | Active Labs | Failures | Health | Hot Nodes (>80%) | Ceph Errors | CCM Fails | Secret Gen |
|---|---|---|---|---|---|---|---|---|---|
| ocp-us-east-1 | — | 4 | 1 | 0 | 100% | 0 | 0 | 0 | Running |
| ocpv-infra01 | Dallas | 1 | 0 | 0 | N/A | 0 | 0 | 8 | Running* |
| ocpv-infra02 | Washington DC | 0 | 0 | 0 | N/A | 0 | 0 | 0 | CrashLoop |
| ocpv01 | Dallas | 120 | 120 | 0 | **100%** | 0 | 2,910 | 8 | Running |
| ocpv03 | Dallas | 59 | 14 | 0 | **100%** | 0 | 722 | 8 | CrashLoop |
| ocpv05 | Dallas | 625 | 567 | 4 | 99.2% | 3 | 2,059 | 8 | CrashLoop |
| ocpv06 | Dallas | 1,033 | 539 | 2 | 99.6% | 6 | 1,518 | 498 | CrashLoop |
| **ocpv07** | **Washington DC** | **603** | **503** | **30** | **94.0%** | **3** | **2,234** | **8** | **CrashLoop** |
| ocpv08 | Dallas | 578 | 520 | 5 | 99.0% | 6 | 1,350 | 8 | Running |
| ocpv09 | Dallas | 562 | 500 | 3 | 99.4% | 0 | 6,137 | 8 | Running |
| ocpv10 | Washington DC | 672 | 630 | 5 | 99.2% | 7 | 10,368 | 8 | Running* |

*infra01 has additional issues detailed below. ocpv10 secret-gen is running but with 37K+ restarts.

## Critical Findings

### 1. Monitoring is blind across the entire platform

`ccm-monitoring-push` is failing on **every lab cluster** (8 Error pods each). On ocpv06 it's accumulating — 498 failed/pending pods. On infra01, the Icinga API returns 401 Unauthorized.

**No cluster is reporting health data to Icinga.** Every other finding on this list is invisible to ops.

### 2. Ceph storage cleanup failing everywhere — 27,298 Error pods

Every lab cluster has failing Ceph cleanup jobs. Storage from destroyed lab environments is not being reclaimed.

| Cluster | Error Pods |
|---|---|
| ocpv10 | 10,368 |
| ocpv09 | 6,137 |
| ocpv01 | 2,910 |
| ocpv07 | 2,234 |
| ocpv05 | 2,059 |
| ocpv06 | 1,518 |
| ocpv08 | 1,350 |
| ocpv03 | 722 |
| **Total** | **27,298** |

Storage will eventually fill up, causing new lab provisioning to fail.

### 3. ocpv07 has the worst lab health — 94.0%

30 labs failing — 6x worse than any other cluster. 6 showroom CrashLoopBackOff (broken lab UIs), plus VM errors and provisioning issues. 3 nodes above 80% CPU with one at 96%.

### 4. 25 nodes above 80% CPU across the platform

| Cluster | Hot Nodes | Worst |
|---|---|---|
| ocpv10 | 7 | 99% |
| ocpv06 | 6 | — |
| ocpv08 | 6 | 88% |
| ocpv05 | 3 | — |
| ocpv07 | 3 | 96% |

ocpv10 and ocpv07 are the highest risk for Summit capacity.

### 5. 13 users have broken lab environments

Showroom Init:CrashLoopBackOff across 5 clusters — these users' lab UIs won't start and have been down for hours to days with no alert:

| Cluster | Broken Labs |
|---|---|
| ocpv07 | 6 |
| ocpv10 | 3 |
| ocpv08 | 2 |
| ocpv05 | 1 |
| ocpv06 | 1 |

### 6. kubernetes-secret-generator broken on 5 of 10 clusters

CrashLoopBackOff on ocpv03, ocpv05, ocpv06, ocpv07, and ocpv-infra02. Running (healthy) on ocpv01, ocpv08, ocpv09, ocp-us-east-1, and ocpv-infra01. ocpv10 is running but with 37,078 restarts.

### 7. Infrastructure cluster (infra01) specific issues

Detailed in separate report:
- Sandbox backups failing (SSH key broken)
- Cost monitor down 56 days
- OCP portal auth broken 38 days
- 3 VMs can't schedule (memory pressure)
- Monitoring push itself broken (Icinga auth)

## The Meta-Finding

The monitoring system is broken across the entire platform. The Ceph cleanup is failing on every cluster. 13 users have broken labs with no alert. 25 nodes are running hot. And nobody knows because the system designed to catch these problems — Icinga monitoring via ccm-monitoring-push — isn't receiving data from any cluster.

This scan took under 5 minutes to run. Every finding is from read-only `oc get` commands. StarGate automates this — deterministic classification, historical tracking, and alerting that doesn't depend on the infrastructure it monitors.
