# StarGate — Summit Provisioning Readiness (7-Day Window)

**Period**: April 30 — May 6, 2026
**Clusters**: 8 lab workload + 2 infra
**Method**: Read-only scan, no modifications

## Provisioning Summary

**3,841 new lab environments provisioned in the last 7 days across 8 clusters.**

| Cluster | New Provisions | Current Failures | Provision Success Rate |
|---|---|---|---|
| ocpv06 | 1,014 | 1 | 99.9% |
| ocpv10 | 636 | 0 | 100% |
| ocpv05 | 567 | 0 | 100% |
| ocpv08 | 528 | 0 | 100% |
| ocpv09 | 520 | 0 | 100% |
| ocpv07 | 510 | 20 | **96.1%** |
| ocpv03 | 46 | 0 | 100% |
| ocpv01 | 20 | 0 | 100% |
| **Total** | **3,841** | **21** | **99.5%** |

## Risk Assessment

### CRITICAL RISK: ocpv07

Worst performing cluster across all metrics:

- **20 currently failing provisions** (highest of any cluster)
  - 8 Windows VMs stuck in ContainerCreating (10 min to 4 hours)
  - 4 Showroom pods still initializing (<30 min — may resolve)
  - 2 dbserver VMs stuck (1-2 hours)
  - 3 OCP control-plane VMs in Error/Pending/ContainerCreating
- **3 nodes above 80% CPU**, one at 96%
- **30 total lab failures** (including older broken labs)
- **94.0% lab health** — worst in the fleet

**Root cause**: CPU pressure. The cluster doesn't have enough compute to handle the provisioning load. VMs are waiting for scheduling, and existing VMs' nested control planes are failing readiness probes due to resource contention.

**Recommendation**: Reduce provisioning load on ocpv07. Redistribute to ocpv01 (100% health, 1-6% CPU, 50 nodes with massive headroom) or ocpv09 (99.4% health, low CPU).

### HIGH RISK: ocpv10

- **9 of 9 compute nodes above 75% CPU, one at 99%**
- Provisions are succeeding (0 recent failures) but the cluster is at the wall
- Any spike in demand will cause scheduling failures
- **10,318 Ceph cleanup error pods** — worst storage cleanup backlog

**Recommendation**: No additional provisioning. This cluster cannot absorb more load.

### MEDIUM RISK: ocpv05, ocpv06, ocpv08

- ocpv05: 3 nodes >80% CPU (new finding — was previously low)
- ocpv06: 6 nodes >80% CPU but handling 1,014 new provisions
- ocpv08: 4 nodes >80% CPU, MetalLB speaker crashing on 2 nodes

These clusters are functional but showing pressure. Monitor for degradation.

### LOW RISK: ocpv01, ocpv03, ocpv09

- ocpv01: 100% health, 50 nodes, 1-6% CPU — **best candidate for overflow**
- ocpv03: 100% health, small cluster, low utilization
- ocpv09: 99.4% health, low CPU

## Platform-Wide Issues Affecting Summit Readiness

### 1. Monitoring is blind — CRITICAL

CCM monitoring push failing on every cluster. Icinga has no health data. If labs fail during Summit, ops won't get alerts from the monitoring system.

**Fix required before Summit**: Rotate Icinga API credentials in all ccm-monitoring-push CronJob configurations.

### 2. Ceph storage not being reclaimed — HIGH

27,298 cleanup error pods across all clusters. Storage from destroyed labs is accumulating. During Summit, rapid provision/destroy cycles will accelerate storage consumption.

**Fix required before Summit**: Investigate Ceph cluster health and cleanup job failures. Clear error pods.

### 3. 17 broken showroom labs — MEDIUM

17 users across 6 clusters have showroom Init:CrashLoopBackOff. Some for nearly 2 months. The `setup` init container (Ansible playbook configuring the lab environment) is failing.

**Fix before Summit**: These are individual lab setup script bugs. Each needs investigation of the setup playbook logs.

### 4. 44 crashlooping VM image importers — HIGH

Base VM image pipeline broken on ocpv03 (38 pods, image source 404), ocpv01 (2 pods), and ocpv06 (3 pods + 1 cross-cluster 401). If these images are needed for Summit labs, new provisions will fail.

**Fix before Summit**: Update image source URLs (404) and fix authentication (401).

### 5. Backup failures — HIGH

Babylon cross-cluster backup on ocp-us-east-1 failing (volume full). Sandbox backup on infra01 failing (SSH key broken).

**Fix before Summit**: Expand backup PVC. Regenerate SSH deploy key.

## What StarGate Would Do Differently

This scan took 5 minutes manually. With StarGate automated:

- **Continuous**: Run every 15 minutes, not once when someone thinks to check
- **Classified**: Every failure gets a named class and recommended remediation, not a raw pod status
- **Prioritized**: ocpv07 at 94% health with 200 attendees in 30 minutes ranks higher than ocpv03 at 100% health with no sessions today
- **Correlated**: "8 Windows VMs stuck on ocpv07" is one systemic issue, not 8 separate alerts
- **Tracked**: If this scan ran yesterday, we'd know which issues are new vs. which have been there for 56 days
- **Alerted**: The monitoring system failure would have been caught immediately — StarGate doesn't depend on Icinga to report that Icinga is down
