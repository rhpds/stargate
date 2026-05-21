# StarGate — Detailed Error Report

**Date**: 2026-05-06
**Clusters**: 10

## 1. Showroom Init CrashLoopBackOff — 17 broken labs

**Root cause**: The `setup` init container fails. Git clone and Antora build succeed (init containers 1 and 2 complete), but the third init container (`setup`) runs an Ansible playbook that configures the lab environment and it fails.

**Specific errors by cluster**:

- **ocpv07 / sandbox-4j87j**: Setup playbook failed on `control` node — `failed=1` on the control host. 4,006 restarts since April 19.
- **ocpv10 / sandbox-l7mmc**: Setup script `setup-builder.sh` exits with rc=125. 15,130 restarts since **March 11** — this lab has been broken for nearly 2 months.
- **ocpv08 / sandbox-gjnp5**: Setup script `setup-control.sh` exits with rc=2 after 2m35s. 7,726 restarts since March 31.

**Pattern**: All failures are in the `setup` init container, not the git clone or Antora build. The setup playbooks are failing against the lab VMs — either the VMs aren't ready when setup runs, or the setup scripts have bugs for specific lab configurations.

**Impact**: 17 users across 6 clusters have completely broken lab UIs. Some have been broken for weeks to months.

## 2. CNV Image Importers CrashLoopBackOff — 44 pods

**Root cause**: Two different errors:

- **ocpv03 (38 pods)**: HTTP 404 — `expected status code 200, got 404`. The source URL for the VM image returns Not Found. The image has been moved or deleted from the source registry.
- **ocpv06 cross-cluster (1 pod, 5,447 restarts)**: HTTP 401 — `expected status code 200, got 401 Unauthorized`. Authentication to the source image registry is failing.

**Impact**: Base VM images cannot be imported. New labs that depend on these images will fail to provision. ocpv03 is the worst — 38 importers crashing means most of that cluster's image pipeline is broken.

## 3. Backup Failures — 2 clusters

**Root cause**: Two different errors:

- **ocp-us-east-1 (Babylon cross-cluster backup)**: `write /dev/stdout: no space left on device`. The backup PVC is full. The backup job tries to dump all AnarchyActions and AnarchyRuns across all namespaces and runs out of disk space.
- **infra01 (Sandbox cluster backup)**: `Load key /tmp/home/.ssh/id_ed25519: error in libcrypto`. SSH key is corrupted or incompatible. Cannot clone the `sandbox-api-configs` repo from GitHub.

**Impact**: No backups running on either cluster. The Babylon backup has likely been failing since the volume filled up. The sandbox backup is failing since the SSH key broke.

## 4. Cost Management Operator — ocpv06

**Root cause**: Operator ran successfully until April 17, then was terminated with exit code -1 on April 22. The pod hasn't been replaced (restart count = 0). Likely killed by OOM or external signal and the deployment didn't recreate it.

**Impact**: No cost management metrics being collected from ocpv06 since April 22 — 14 days of missing data.

## 5. MetalLB Speaker — ocpv07 and ocpv08

**Root cause**: Speaker pod starts, joins the memberlist cluster, then immediately receives a shutdown signal and exits cleanly. This repeats every ~3 minutes. The pod is being killed externally — either by a liveness probe failure, an OOM kill, or a node-level issue.

**Affected nodes**: `ocp-virt7-host` (ocpv07), `ocp-virt8-host` and `ocp-virt8-host3` (ocpv08).

**Impact**: MetalLB load balancer IP assignment may be unreliable on these nodes. Could affect external access to lab services.

## 6. VM Control Plane Errors — ocpv07

**Root cause**: Readiness probe timeout — `Get "https://10.129.37.214:6443/healthz": context deadline exceeded`. The VM is running a nested OCP control plane but the API server inside the VM is not responding to health checks. This is a performance issue — the VM's API server is overloaded or the host node is under too much CPU pressure (ocpv07 has 3 nodes above 80% CPU).

**Impact**: 2 lab environments with nested OCP clusters have unhealthy control planes.

## 7. CCM Monitoring Push — ALL clusters

**Root cause** (from infra01 logs): `401 {"error":401,"status":"Unauthorized. Please check your user credentials."}`. Icinga API credentials have expired or been rotated without updating the CronJob configuration.

**Impact**: No monitoring data reaching Icinga from any cluster. All health alerts are blind.

## 8. Ceph Cleanup — ALL lab clusters (27,298 Error pods)

**Root cause**: Cleanup jobs that reclaim Ceph RBD storage from destroyed lab environments are failing. The jobs attempt to find and remove RBD images, CSI snapshots, and trash volumes, but error out. Likely Ceph cluster health issue or permission change.

**Impact**: Storage from destroyed labs is not being reclaimed. Ceph storage will fill up over time, eventually preventing new lab provisioning.

## 9. Babylon Cross-Cluster Backup — ocp-us-east-1

**Root cause**: `no space left on device`. The backup PVC is full. Backing up all AnarchyActions and AnarchyRuns YAML across the entire platform exceeds the volume capacity.

**Impact**: No Babylon CRD backups. If AnarchySubject/Action data is lost, provisioning state cannot be recovered.

## Summary by Root Cause

| Root Cause | Clusters | Pods | Duration |
|---|---|---|---|
| Showroom setup playbook failures | 6 | 17 | Days to months |
| VM image source 404/401 | 3 | 44 | Days to weeks |
| Icinga auth expired | All | 8 per cluster | Hours+ |
| Ceph cleanup failures | All lab | 27,298 | Ongoing |
| SSH key broken (backup) | 1 | 6 | Hours+ |
| Backup volume full | 1 | 4 | Unknown |
| Cost operator killed | 1 | 1 | 14 days |
| MetalLB speaker killed | 2 | 3 | 14 days |
| VM API server overloaded | 1 | 2 | Hours |
