# StarGate Cluster Health Report — Infrastructure Clusters

**Scanned**: 2026-05-06

| Cluster | Location | Namespaces | Nodes | Worker Memory | Issues |
|---|---|---|---|---|---|
| `cluster.example.com` | Dallas | 75 | 9 | 49-52% | 7 findings |
| `ocpv-infra02.wdc07.infra.demo.redhat.com` | Washington DC | 30 | 9 | 26-37% | 1 finding |

## Critical Findings

### 1. Sandbox cluster backups failing every hour
- **Namespace**: `babylon-sandbox-api`
- **Classification**: `ssh_key_error`
- **Detail**: SSH key rejected — `"Load key /tmp/home/.ssh/id_ed25519: error in libcrypto"`. Cannot clone `sandbox-api-configs` from GitHub. Every hourly backup CronJob has failed (6 consecutive Error pods visible).
- **Impact**: No cluster backups running. Data loss risk if sandbox database corrupts or needs recovery.
- **Remediation**: Regenerate or replace the SSH deploy key for the `sandbox-api-configs` repo and update the `sandbox-backup` build/secret.

### 2. Monitoring push to Icinga failing for 7+ hours
- **Namespace**: `ccm-monitoring`
- **Classification**: `auth_failure`
- **Detail**: Icinga API returning `401 Unauthorized: "Please check your user credentials."` Every hourly `ccm-monitoring-push` CronJob has failed since at least 14:00 UTC (8 consecutive Error pods visible).
- **Impact**: Icinga has no fresh monitoring data from this cluster. Health alerts will not fire. This means the monitoring system that should catch problems is itself broken — silent failure.
- **Remediation**: Update Icinga API credentials in the `ccm-monitoring-push` CronJob configuration.

## High Findings

### 3. Cost monitoring data service stuck for 56 days
- **Namespace**: `cost-monitor`
- **Classification**: `volume_mount_stuck`
- **Detail**: `cost-data-service` pod has been in `ContainerCreating` since March 11, 2026. No events recorded — likely a PVC or secret mount that was never resolved. The deployment shows 1 desired replica but 0 available.
- **Impact**: Cost monitoring data service has not been running for nearly 2 months. Cloud cost data not being collected or served.
- **Remediation**: Check PVC `data-cache-pvc` binding status and `gcp-credentials` secret. Delete and recreate the pod.

### 4. OCP Portal OAuth proxy broken for 38 days
- **Namespace**: `ocp-portal`
- **Classification**: `image_pull_failure`
- **Detail**: `op-which` pod has been in `ImagePullBackOff` for 38 days, attempting to pull `quay.io/openshift/oauth-proxy:4.15`. Over 10,751 pull attempts. The image tag likely doesn't exist or the registry is inaccessible.
- **Impact**: OCP portal OAuth proxy not running. Portal authentication may be completely broken.
- **Remediation**: Verify the `oauth-proxy:4.15` tag exists on `quay.io/openshift`. Update to a current tag (e.g., `4.17`).

## Low Findings

### 5. Stale debug pod in aap2-prod0
- **Namespace**: `aap2-prod0`
- **Classification**: `image_pull_failure`
- **Detail**: `image-debug-p44ls` has been in `ImagePullBackOff` for 36 days. This appears to be a leftover debug pod, not a running service.
- **Impact**: No operational impact — stale artifact.
- **Remediation**: `oc delete pod image-debug-p44ls -n aap2-prod0`

## Healthy Namespaces

| Namespace | Deployments | Routes | Endpoints | Status |
|---|---|---|---|---|
| `parsec` | All healthy | Serving | Ready | OK |
| `rcars-prod` | All healthy | Serving | Ready | OK |
| `aap2-prod0` | All healthy | Serving | Ready | OK (aside from stale debug pod) |

### 6. Three VMs can't schedule — cluster memory pressure
- **Namespaces**: `icinga`, `rcb`, `rh-ace-aiops`
- **Classification**: `insufficient_memory`
- **Detail**: Three VMs (`icinga-infra`, `rcb-rhel9`, `rdsjumphost`) stuck in `Pending`. FailedScheduling events show "Insufficient memory" on all 3 worker nodes. Workers are at 49-52% memory usage but VM resource requests exceed remaining allocatable.
- **Impact**: Icinga monitoring VM not running (monitoring further degraded — compounds the ccm-monitoring auth failure). RCB and AIOps jump host environments unavailable.
- **Remediation**: Either increase worker node memory or reduce VM resource requests. Given the Icinga VM is critical infrastructure, it should be prioritized.

### 7. Labagator frontend builds failed (transient — recovered)
- **Namespaces**: `labagator-dev`, `labagator-prod`
- **Classification**: `build_transient_failure`
- **Detail**: 10 frontend build pods in Error state across dev and prod from ~7 hours ago. CRI-O container logs unrecoverable. Latest builds (3 hours ago) succeeded — the issue self-resolved.
- **Impact**: No current impact — builds recovered. Failed build pods are stale artifacts.
- **Remediation**: No action needed. Clean up old build pods with `oc delete pod -l openshift.io/build.name -n labagator-dev --field-selector status.phase=Failed`.

## Healthy Namespaces

| Namespace | Deployments | Routes | Endpoints | Status |
|---|---|---|---|---|
| `parsec` | All healthy | Serving | Ready | OK |
| `parsec-dev` | All healthy | Serving | Ready | OK |
| `rcars-prod` | All healthy | Serving | Ready | OK |
| `rcars-dev` | All healthy | Serving | Ready | OK |
| `aap2-prod0` | All healthy | Serving | Ready | OK (stale debug pod) |
| `demolition-prod` | All healthy (API×2, frontend×3, cleanup×2) | Serving | Ready | OK |
| `demolition-dev` | All healthy | Serving | Ready | OK |
| `labagator-prod` | All healthy (backend×2) | Serving | Ready | OK (stale build pods) |
| `labagator-dev` | All healthy (backend×1) | Serving | Ready | OK (stale build pods) |
| `overwatch-prod` | All healthy | Serving | Ready | OK |
| `analytics-superset-prod` | All healthy (7 pods) | — | — | OK |
| `analytics-superset-stage` | All healthy (7 pods) | — | — | OK |
| `acme-bifrost` | All healthy (18 pods) | — | — | OK |
| `publishing-house-dev` | All healthy | Serving | Ready | OK |
| `mlflow` | All healthy (4 pods) | — | — | OK |
| `showroom-soundcheck-dev` | All healthy | Serving | Ready | OK |
| `ibmcloud-portal` | All healthy (7 pods) | — | — | OK |
| `github-runner` | All healthy (2 pods) | — | — | OK |
| `route53-proxy` | All healthy (3 pods) | — | — | OK |

## Cluster Resources

| Node | Role | CPU Usage | Memory Usage |
|---|---|---|---|
| ocp-infra01-worker00 | compute | 1% | 49% |
| ocp-infra01-worker01 | compute | 1% | 51% |
| ocp-infra01-worker02 | compute | 2% | 52% |
| ocp-infra01-cp00 | control-plane | 7% | 46% |
| ocp-infra01-cp01 | control-plane | 1% | 34% |
| ocp-infra01-cp02 | control-plane | 4% | 49% |
| ocp-infra01-ceph00 | ceph/infra | 3% | 18% |
| ocp-infra01-ceph01 | ceph/infra | 29% | 30% |
| ocp-infra01-ceph02 | ceph/infra | 14% | 27% |

Worker nodes are at 49-52% memory — not critical for container workloads but insufficient for additional VM scheduling. CPU utilization is low (1-2%).

## Meta-Finding

The two most critical issues — broken backups and broken monitoring push — are **silent failures**. The monitoring system (`ccm-monitoring`) that should detect the backup failure (`babylon-sandbox-api`) is itself broken. The Icinga VM that runs the monitoring can't even schedule due to memory pressure. That's a three-layer failure chain:

1. Icinga VM can't schedule (insufficient memory)
2. `ccm-monitoring-push` can't authenticate to Icinga (stale credentials)
3. `sandbox-cluster-backup` fails silently (broken SSH key)

Nobody knows about any of these because each system that should catch the one below it is also broken. This is exactly what a centralized validation layer prevents — it doesn't depend on the systems it monitors to report their own failures.

## Cross-Cluster Finding: kubernetes-secret-generator

**Both infra clusters** have the same `kubernetes-secret-generator` operator in CrashLoopBackOff:

| Cluster | Restarts | Duration | Image |
|---|---|---|---|
| infra01 (dal12) | 11,621 | 22 days | `quay.io/mittwald/kubernetes-secret-generator:v3.4.0` |
| infra02 (wdc07) | 11,625 | 22 days | `quay.io/mittwald/kubernetes-secret-generator:v3.4.0` |

Same image, same operator-sdk version (`v0.16.0`), same Go version (`go1.15.15`), same behavior: starts, acquires leader lock, then crashes immediately. This is a **systemic issue** — the operator version is likely incompatible with the current OpenShift version on both clusters.

**Classification**: `operator_crash_systemic`
**Impact**: Any secrets managed by this operator are not being auto-generated or rotated.
**Remediation**: Upgrade `kubernetes-secret-generator` to a version compatible with the current OpenShift/Kubernetes version, or remove if no longer needed.

## ocpv-infra02 Summary

infra02 is healthy. 678 running pods, 30 namespaces, only 1 issue (the shared secret-generator crash). Worker nodes at 26-37% memory — significantly less pressure than infra01's 49-52%. infra02 hosts fewer services (no Demolition, no Labagator, no Parsec, no RCARS, no Overwatch, no cost-monitor).

## Overall Summary

| Severity | Count | Details |
|---|---|---|
| CRITICAL | 2 | Sandbox backups (SSH key), monitoring push (Icinga auth) |
| HIGH | 3 | Cost monitor (56 days), OCP portal auth (38 days), VM scheduling (memory) |
| SYSTEMIC | 1 | kubernetes-secret-generator crashing on both infra clusters (22 days) |
| LOW | 2 | Stale debug pod, transient build failures (recovered) |
| **Total findings** | **8** | Across 105 namespaces on 2 clusters |
| **Healthy namespaces** | **19+** | Demolition, Labagator, Parsec, RCARS, Overwatch, MLflow, etc. |
