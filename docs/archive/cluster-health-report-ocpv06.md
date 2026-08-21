# StarGate Cluster Health Report — ocpv06

**Cluster**: `cluster.example.com`
**Scanned**: 2026-05-06
**Type**: CNV lab workload cluster

## Lab Health Summary

| Metric | Value |
|---|---|
| Total sandbox namespaces | 1,013 |
| Namespaces with running pods | 517 |
| Namespaces with unhealthy pods | 10 |
| **Lab health rate** | **98.0%** |

## Lab Failures (10 namespaces)

### Actively Provisioning (8 — likely transient)

These VMs and DataVolume imports are in `ContainerCreating` — they may be actively provisioning. Need to check if they've been stuck or are just starting up.

| Namespace | Pod | Type | Status |
|---|---|---|---|
| `sandbox-54vkk-zt-rhelbu` | importer-prime | DataVolume import | ContainerCreating |
| `sandbox-5sfmb-ocp4-cluster` | virt-launcher-allinone | VM starting | ContainerCreating |
| `sandbox-dxcv9-zt-rhelbu` | virt-launcher-rhel | VM starting | ContainerCreating |
| `sandbox-fm7z9-zt-rhelbu` | virt-launcher-rhel2 | VM starting | ContainerCreating |
| `sandbox-fzt9c-zt-rhelbu` | virt-launcher-rhel | VM starting | ContainerCreating |
| `sandbox-htvmz-zt-rhelbu` | virt-launcher-rhel | VM starting | ContainerCreating |
| `sandbox-rhghm-zt-rhelbu` | importer-prime | DataVolume import | ContainerCreating |
| `sandbox-xq4bh-ocp4-cluster` | virt-launcher-bastion | VM starting | ContainerCreating |
| `sandbox-zndpz-zt-ansiblebu` | virt-launcher-windows | VM starting | ContainerCreating |

**Classification**: `vm_provisioning` — likely transient. StarGate's watch mode would distinguish "still provisioning" from "stuck" by checking if the state persists beyond the rubric timeout (600s for VMs).

### Broken Lab (1 — real failure)

| Namespace | Pod | Status | Duration |
|---|---|---|---|
| `sandbox-vvdmj-zt-ansiblebu` | showroom | Init:CrashLoopBackOff | **2 days 14 hours** |

**Classification**: `showroom_init_crashloop`
**Detail**: Showroom pod has 7 containers but the init container (`git-cloner`) completed successfully. A subsequent init container is crashlooping. The lab UI has been down for over 2 days.
**Impact**: This user's lab environment is completely unusable — they can't access the showroom UI.
**Remediation**: Check init container logs. The git clone succeeded but a content build or setup step is failing.

## Platform Issues

### CRITICAL: ccm-monitoring CronJob pod accumulation
- **Pod count**: 497 (and growing hourly)
- **Classification**: `cronjob_cleanup_failure`
- **Detail**: The `ccm-monitoring-push` CronJob runs hourly but its `failedJobsHistoryLimit` and `successfulJobsHistoryLimit` aren't set low enough (or at all). Failed pods accumulate indefinitely. 8 are in Error, 10 in ContainerCreating, the rest Pending.
- **Impact**: Resource waste and namespace pollution. Eventually hits pod quota limits.
- **Remediation**: Set `failedJobsHistoryLimit: 3` and `successfulJobsHistoryLimit: 3` on the CronJob. Clean up existing pods: `oc delete pods -n ccm-monitoring --field-selector status.phase=Failed`

### CRITICAL: cleanup namespace — 1,509 Error pods
- **Classification**: `ceph_cleanup_failure`
- **Detail**: Ceph storage cleanup jobs (`cleanup-ceph-sandbox-*`) are failing. These jobs clean up RBD images and CSI snapshots for destroyed lab environments. Many are erroring out.
- **Impact**: Ceph storage not being reclaimed from destroyed labs. Storage will fill up over time.
- **Remediation**: Investigate Ceph cleanup job logs. Check Ceph cluster health. Clean up failed pods.

### HIGH: cnv-images importer crash (2 days)
- **Classification**: `image_import_crashloop`
- **Detail**: 3 importer-prime pods in CrashLoopBackOff for 2 days 6 hours. These import base VM images used by new lab provisioning.
- **Impact**: New labs that need these base images may fail to provision.
- **Remediation**: Check importer logs for the specific image import failure.

### HIGH: ocp4-cluster-cnv-us-south-ocp-1 importer crash (19 days)
- **Classification**: `image_import_crashloop`
- **Detail**: 1 importer-prime pod in CrashLoopBackOff for 19 days. 5,436 restarts.
- **Impact**: Cross-cluster image import to cnv-us-south-ocp-1 is broken.
- **Remediation**: Check if the source image exists and the target cluster is reachable.

### MEDIUM: costmanagement-metrics-operator (25 days)
- **Classification**: `operator_error`
- **Detail**: Operator pod in Error state for 25 days. Container logs unrecoverable.
- **Impact**: Cost management metrics not being collected for this cluster.
- **Remediation**: Delete and let the deployment recreate the pod.

### SYSTEMIC: kubernetes-secret-generator (22 days)
- Same issue as infra01 and infra02. CrashLoopBackOff with `quay.io/mittwald/kubernetes-secret-generator:v3.4.0`. **All three clusters affected.**

## Cross-Cluster Pattern

`kubernetes-secret-generator` is crashing on every cluster we've scanned:

| Cluster | Duration | Restarts |
|---|---|---|
| ocpv-infra01 (dal12) | 22 days | 11,621 |
| ocpv-infra02 (wdc07) | 22 days | 11,625 |
| ocpv06 (dal10) | 22 days | — |

Same image, same version, same behavior. This is a platform-wide issue affecting all RHDP clusters.
