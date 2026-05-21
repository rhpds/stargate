# StarGate Platform Health Report

**Scanned**: 2026-05-06 ~23:00 UTC
**Clusters**: 10 (2 infra + 8 lab workload)
**Method**: Read-only — no modifications made
**Windows**: Current state, last 12 hours, last 7 days

## Platform Overview

| Cluster | Location | Sandbox NS | Active Labs | Failing | Health | New (12h) | Fail (12h) | New (7d) | Hot Nodes | Ceph Errors | CCM | Secret Gen |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ocp-us-east-1 | — | 4 | 1 | 0 | 100% | 0 | 0 | 0 | 0 | 0 | 0 | Running |
| ocpv-infra01 | Dallas | 1 | 0 | 0 | N/A | 0 | 0 | 0 | 0 | 0 | 8 | Running |
| ocpv-infra02 | DC | 0 | 0 | 0 | N/A | 0 | 0 | 0 | 0 | 0 | 0 | Running |
| ocpv01 | Dallas | 0 | 0 | 0 | N/A | 0 | 0 | 0 | 0 | 2,960 | 8 | Running |
| ocpv03 | Dallas | 59 | 13 | 0 | 100% | 6 | 0 | 46 | 0 | 722 | 8 | CrashLoop |
| ocpv05 | Dallas | 623 | 564 | 4 | 99.3% | 269 | 0 | 568 | 2 | 2,064 | 8 | CrashLoop |
| ocpv06 | Dallas | 1,031 | 535 | 2 | 99.6% | 246 | 0 | 1,006 | 5 | 1,530 | 499 | CrashLoop |
| **ocpv07** | **DC** | **592** | **495** | **20** | **95.9%** | **199** | **11** | **510** | **3** | **2,236** | **8** | **CrashLoop** |
| ocpv08 | Dallas | 581 | 522 | 6 | 98.9% | 246 | 0 | 532 | 7 | 1,352 | 8 | Running |
| ocpv09 | Dallas | 571 | 499 | 4 | 99.2% | 154 | 0 | 519 | 0 | 6,140 | 8 | Running |
| ocpv10 | DC | 677 | 628 | 5 | 99.2% | 294 | 0 | 638 | 6 | 10,406 | 8 | CrashLoop |

## Platform Totals

| Metric | Current | Last 12h | Last 7d |
|---|---|---|---|
| Active labs | 3,257 | — | — |
| New provisions | — | 1,414 | 4,319 |
| Failing labs | 41 | 11 | — |
| **Lab health rate** | **98.7%** | **99.2% (provision rate)** | **99.5%** |
| Ceph cleanup errors | 27,410 | — | — |
| Hot nodes (>80% CPU) | 23 | — | — |
| Showroom CrashLoopBackOff | 14 | — | — |

## Last 12 Hours

**1,414 new provisions. Only ocpv07 producing failures.**

| Cluster | Provisions | Failures | Status |
|---|---|---|---|
| ocpv10 | 294 | 0 | OK |
| ocpv05 | 269 | 0 | OK |
| ocpv06 | 246 | 0 | OK |
| ocpv08 | 246 | 0 | OK |
| ocpv07 | 199 | **11** | **FAILING** |
| ocpv09 | 154 | 0 | OK |
| ocpv03 | 6 | 0 | OK |

**ocpv07 failure breakdown** (last 12h):
- 6 Windows VMs stuck ContainerCreating (10min-2hrs) — CPU scheduling delay
- 4 Showroom pods initializing (<30min) — likely transient
- 1 OCP control-plane VM Pending — can't schedule

**Root cause**: CPU pressure on ocpv07. 3 nodes above 80%, one at 96%.

## Critical Findings

### 1. Monitoring blind across all clusters — CRITICAL

CCM monitoring push failing on every lab cluster. Icinga receives no health data. Confirmed root cause: `401 Unauthorized` — API credentials expired. 499 accumulated failed pods on ocpv06 alone.

**Fix**: Rotate Icinga API credentials in ccm-monitoring-push CronJob configs on all clusters.

### 2. Ceph storage not reclaimed — 27,410 error pods — CRITICAL

Every lab cluster has failing Ceph cleanup jobs. Storage from destroyed labs is not being freed.

| Cluster | Error Pods |
|---|---|
| ocpv10 | 10,406 |
| ocpv09 | 6,140 |
| ocpv01 | 2,960 |
| ocpv07 | 2,236 |
| ocpv05 | 2,064 |
| ocpv06 | 1,530 |
| ocpv08 | 1,352 |
| ocpv03 | 722 |

**Fix**: Investigate Ceph cluster health. Fix cleanup job failures. Clear error pods.

### 3. ocpv07 — only cluster failing provisions — CRITICAL

95.9% lab health (worst). 11 failures in last 12 hours. 20 total current failures. CPU maxed on 3 nodes.

**Fix**: Redirect provisioning to ocpv01 (0% utilized, 50 nodes).

### 4. ocpv10 — at CPU capacity — HIGH

6 nodes above 80% CPU. Zero provision failures currently, but no headroom. One spike and it breaks.

### 5. 14 broken showroom labs — HIGH

Users with broken lab UIs across 6 clusters. Some for weeks. All caused by `setup` init container Ansible playbook failures. No alerts fired.

| Cluster | Broken Labs | Longest Down |
|---|---|---|
| ocpv07 | 5 | 17 days |
| ocpv05 | 3 | — |
| ocpv10 | 2 | — |
| ocpv09 | 2 | — |
| ocpv08 | 1 | 36 days |
| ocpv06 | 1 | 2.5 days |

### 6. kubernetes-secret-generator — 5 of 10 clusters — HIGH

CrashLoopBackOff on ocpv03, ocpv05, ocpv06, ocpv07, ocpv10. Running on others but with thousands of restarts.

### 7. 44 CNV image importers crashing — HIGH

Base VM image pipeline broken. Source URLs returning 404 (images moved) or 401 (auth broken). Worst: ocpv03 with 38 crashlooping importers.

### 8. Backup failures — HIGH

- ocp-us-east-1: Babylon cross-cluster backup — `no space left on device`
- ocpv-infra01: Sandbox backup — SSH key broken (`error in libcrypto`)

### 9. Infrastructure cluster issues (infra01) — MIXED

- Cost monitor down 56 days (ContainerCreating — PVC issue)
- OCP portal OAuth broken 38 days (ImagePullBackOff — wrong image tag)
- 3 VMs can't schedule (insufficient memory)
- Monitoring push broken (same Icinga auth issue as all clusters)

## Error Root Causes

| Root Cause | Classification | Clusters | Pods | Fix |
|---|---|---|---|---|
| Icinga credentials expired | `monitoring_auth_failure` | All | 550+ | Rotate credentials |
| Ceph cleanup failures | `ceph_cleanup_systemic` | All lab | 27,410 | Investigate Ceph health |
| CPU pressure (ocpv07) | `cluster_cpu_pressure` | 1 | — | Redirect to ocpv01 |
| Showroom setup playbook failures | `showroom_init_crashloop` | 6 | 14 | Debug per-lab setup scripts |
| VM image source 404/401 | `image_import_failure` | 3 | 44 | Update URLs/fix auth |
| kubernetes-secret-generator crash | `operator_crash_systemic` | 5 | 5 | Upgrade operator version |
| Backup volume full | `backup_storage_full` | 1 | 4 | Expand PVC |
| Backup SSH key broken | `ssh_key_error` | 1 | 6 | Regenerate deploy key |
| MetalLB speaker killed | `network_operator_crashloop` | 2 | 3 | Investigate node issue |
| Cost operator OOM | `operator_error` | 1 | 1 | Increase memory limit |
| Portal image tag wrong | `image_pull_failure` | 1 | 1 | Update to current tag |
| VM scheduling (memory) | `insufficient_memory` | 1 | 3 | Add node memory |

## Summit Readiness Verdict

**Overall platform health: 98.7%** — 3,257 active labs, 41 failing.

**Immediate actions required**:
1. Fix Icinga credentials — restore monitoring visibility
2. Redirect ocpv07 provisioning to ocpv01 — stop producing failures
3. Investigate Ceph cleanup — 27K error pods accumulating storage

**Before Summit**:
4. Fix VM image importer sources (404/401) — blocks new lab provisioning
5. Clean up broken showroom labs — 14 users affected
6. Expand Babylon backup PVC — backups not running
7. Fix sandbox backup SSH key — backups not running

**This scan was read-only and took under 5 minutes across 10 clusters.**
