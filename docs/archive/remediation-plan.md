# Remediation Plan — Last 12 Hours

## Immediate (do now)

### 1. Fix Icinga credentials — restore monitoring visibility

All clusters are pushing monitoring data to Icinga and getting `401 Unauthorized`. Nobody sees any alert until this is fixed.

```bash
# On every lab cluster, update the ccm-monitoring-push CronJob with new credentials
# Get current CronJob config
oc get cronjob ccm-monitoring-push -n ccm-monitoring -o yaml

# Update the Icinga API credentials (secret or env var depending on config)
# Then delete the accumulated failed pods
oc delete pods -n ccm-monitoring --field-selector status.phase=Failed
```

**Owner**: Monitoring/Icinga team
**Time**: 30 minutes
**Risk**: None — read-only monitoring push

### 2. Fix Babylon cross-cluster backup — disk full

```bash
# On ocp-us-east-1, check PVC usage
oc exec -n babylon-cross-cluster-backup <backup-pod> -- df -h /backup

# Option A: Expand the PVC
oc patch pvc <backup-pvc> -n babylon-cross-cluster-backup -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

# Option B: Prune old backups
oc exec -n babylon-cross-cluster-backup <backup-pod> -- find /backup -mtime +7 -delete
```

**Owner**: Babylon team
**Time**: 15 minutes
**Risk**: None

### 3. Fix sandbox backup SSH key — infra01

```bash
# Regenerate the SSH deploy key
ssh-keygen -t ed25519 -f /tmp/sandbox-backup-key -N ""

# Add the public key to https://github.com/rhpds/sandbox-api-configs/settings/keys

# Update the secret in the namespace
oc create secret generic sandbox-backup-ssh \
  --from-file=id_ed25519=/tmp/sandbox-backup-key \
  -n babylon-sandbox-api --dry-run=client -o yaml | oc apply -f -

# Delete failed pods
oc delete pods -n babylon-sandbox-api --field-selector status.phase=Failed
```

**Owner**: Sandbox team
**Time**: 15 minutes
**Risk**: None

### 4. Clean up failed Ceph cleanup pods — all clusters

27,298 Error pods accumulating. They won't fix themselves but they're consuming API server resources.

```bash
# On each lab cluster
oc delete pods -n cleanup --field-selector status.phase=Failed
```

**Owner**: Storage/Ceph team
**Time**: 5 minutes per cluster
**Risk**: None — deleting already-failed pods

## Short-term (this week, before Summit)

### 5. Investigate Ceph cleanup root cause

Deleting failed pods is cleanup. The jobs are still failing every run. Need to find why.

```bash
# Check a recent failure log
oc logs <most-recent-failed-cleanup-pod> -n cleanup

# Check Ceph cluster health
oc exec -n openshift-storage <ceph-tools-pod> -- ceph health detail
oc exec -n openshift-storage <ceph-tools-pod> -- ceph osd pool ls detail
```

**Owner**: Storage/Ceph team
**Time**: 2-4 hours to diagnose
**Risk**: None — investigation only

### 6. Reduce Prometheus resource usage on hot clusters

Prometheus is consuming 13-24 CPU cores per cluster. On ocpv06 it's the #1 and #2 CPU consumer.

```bash
# Check current retention and scrape interval
oc get prometheus k8s -n openshift-monitoring -o jsonpath='{.spec.retention}'
oc get prometheus k8s -n openshift-monitoring -o jsonpath='{.spec.scrapeInterval}'

# Reduce retention from default 15d to 3d on hot clusters
oc patch prometheus k8s -n openshift-monitoring --type merge -p '{"spec":{"retention":"3d"}}'

# Or reduce replicas from 2 to 1 on non-critical clusters
oc patch prometheus k8s -n openshift-monitoring --type merge -p '{"spec":{"replicas":1}}'
```

**Owner**: Monitoring team
**Time**: 30 minutes
**Risk**: Low — reduces monitoring history, not real-time alerting

### 7. Reduce Splunk log forwarder resource usage

`splunk-clf` consuming 7-10 CPU cores per cluster. Review if all log sources are necessary during Summit.

```bash
# Check what's being forwarded
oc get clusterlogforwarder -n openshift-logging -o yaml

# Consider filtering to only forward Warning/Error level during peak
```

**Owner**: Logging team
**Time**: 1 hour
**Risk**: Low — reduces log volume, not log availability

### 8. Fix CNV image importer sources

44 crashlooping importers across 3 clusters. Two root causes:

**404 — image source moved** (ocpv03, 38 pods):
```bash
# Find what URL it's trying to pull
oc get datavolume <dv-name> -n cnv-images -o jsonpath='{.spec.source.http.url}'

# Update to correct URL or delete stale DataVolumes
oc delete datavolume <stale-dv> -n cnv-images
```

**401 — auth broken** (ocpv06 cross-cluster, 1 pod):
```bash
# Check the source credentials
oc get datavolume <dv-name> -n ocp4-cluster-cnv-us-south-ocp-1 -o yaml | grep -A5 secretRef

# Update the secret with valid credentials
```

**Owner**: CNV/image team
**Time**: 1-2 hours
**Risk**: None — fixing broken importers

### 9. Fix installation-iso PVC contention

273 warning events across 4 clusters for `installation-iso` and `scale-iso` PVCs. These ISOs are needed by every new nested OCP cluster lab.

```bash
# Check if the ISOs exist and are accessible
oc get datavolume installation-iso -n cnv-images -o yaml
oc get pvc installation-iso -n cnv-images -o yaml

# If bound but slow: check Ceph IOPS and throughput
# If multiple pods pulling same ISO: consider pre-caching or increasing PVC IOPS
```

**Owner**: CNV/storage team
**Time**: 2-4 hours
**Risk**: None — investigation

### 10. Clean up broken showroom labs

17 users with CrashLoopBackOff showroom pods. Each needs individual investigation of the `setup` init container.

```bash
# For each broken lab, get the setup container logs
oc logs <showroom-pod> -n <sandbox-ns> -c setup --previous --tail=50

# Common fix: delete the pod and let it recreate
oc delete pod <showroom-pod> -n <sandbox-ns>

# If setup script consistently fails: fix the setup playbook in the lab's showroom repo
```

**Owner**: Lab content owners (per lab)
**Time**: 30 minutes per lab
**Risk**: None — restarting a broken pod

## Critical — Provisioning Concurrency

### The Problem

Right now, 1,096 nested OCP cluster labs are running simultaneously across 6 clusters, producing 5,488 VMs. No concurrency limit exists.

| Cluster | Concurrent Labs | Running VMs | Compute Nodes | VMs/Node | Avg CPU |
|---|---|---|---|---|---|
| ocpv09 | 248 | 979 | 40 | **24.5** | **30%** |
| ocpv08 | 137 | 717 | 15 | 47.8 | 61% |
| ocpv07 | 170 | 870 | 15 | 58.0 | 53% |
| ocpv06 | 157 | 816 | 15 | 54.4 | 65% |
| ocpv10 | 193 | 1,038 | 15 | **69.2** | **68%** |
| ocpv05 | 191 | 1,068 | 15 | **71.2** | 58% |

**ocpv09 is healthy because it has 40 nodes — 24.5 VMs per node, 30% CPU.** Every other cluster has 15 nodes with 48-71 VMs per node and is running hot.

**The threshold is clear**: clusters with <30 VMs/node are healthy. Clusters with >50 VMs/node are saturating.

### The Fix — Concurrency Limits

**Option A — Per-cluster VM cap** (fastest):

Set a maximum concurrent ocp4-cluster labs per cluster based on node count:

| Cluster | Nodes | Safe VM Cap | Safe Lab Cap (~5 VMs/lab) | Current Labs | Over By |
|---|---|---|---|---|---|
| ocpv05 | 15 | 450 | 90 | 191 | **101** |
| ocpv06 | 15 | 450 | 90 | 157 | **67** |
| ocpv07 | 15 | 450 | 90 | 170 | **80** |
| ocpv08 | 15 | 450 | 90 | 137 | **47** |
| ocpv09 | 40 | 1,200 | 240 | 248 | 8 |
| ocpv10 | 15 | 450 | 90 | 193 | **103** |

At 30 VMs/node (the healthy threshold from ocpv09), the 15-node clusters should cap at ~90 concurrent ocp4-cluster labs. They're all running 1.5-2x that.

**Option B — CPU-based admission** (better):

Before placing a new ocp4-cluster lab, check cluster-scheduler. If avg CPU > 70%, redirect to a cluster with headroom. This is what StarGate's cluster-health gate does.

**Option C — Staggered provisioning** (best for Summit):

Instead of provisioning all labs simultaneously, stagger by session time:
- Only provision labs for the next session window (e.g., next 2 hours)
- Destroy completed session labs before provisioning next batch
- This is what Labagator's schedule data enables — but nobody uses it for provisioning decisions today

### Immediate Action

Reduce concurrent load on the hottest clusters:
1. Stop new ocp4-cluster provisioning on ocpv10 (69 VMs/node, 68% avg CPU) and ocpv05 (71 VMs/node)
2. Direct new provisions to ocpv09 (24.5 VMs/node, 30% CPU, 40 nodes, massive headroom)
3. If labs can be destroyed and re-provisioned closer to session time, destroy idle labs on hot clusters now

## Medium-term (before Summit, capacity planning)

### 11. Implement capacity gate for ocp4-cluster provisioning

This is the root cause of all CPU-related failures. No gate exists to prevent overprovisioning.

**Option A — Quick**: Set resource quotas per namespace
```bash
# Limit total CPU per sandbox namespace
oc create quota sandbox-limit -n <sandbox-ns> --hard=requests.cpu=40,limits.cpu=50
```

**Option B — Better**: Configure cluster-scheduler thresholds
```
# In cluster-scheduler config, set max CPU threshold
# Reject new ocp4-cluster placements when cluster CPU > 75%
```

**Option C — Best**: StarGate cluster-health gate
```
# Before provisioning, evaluate:
#   cluster_reachable: true
#   cpu_usage_acceptable: < 80%
#   memory_usage_acceptable: < 80%
#   no_critical_alerts: true
# If gate fails, redirect to a cluster with headroom
```

**Owner**: Platform/capacity team
**Time**: Option A: 1 hour. Option B: 4 hours. Option C: already built, needs deployment.
**Risk**: Option A may block legitimate large labs. Options B/C are smarter.

### 12. Upgrade kubernetes-secret-generator

CrashLoopBackOff on 5 of 10 clusters. Operator version `v3.4.0` with `operator-sdk v0.16.0` and `go1.15.15` is incompatible with current OCP.

```bash
# Check if newer version exists
# quay.io/mittwald/kubernetes-secret-generator — latest is likely v3.5+

# Update the deployment image
oc set image deployment/kubernetes-secret-generator \
  kubernetes-secret-generator=quay.io/mittwald/kubernetes-secret-generator:v3.5.0 \
  -n kubernetes-secret-generator
```

**Owner**: Platform team
**Time**: 30 minutes
**Risk**: Low — operator manages secret generation, upgrade should be compatible

### 13. Fix infra01 specific issues

**Cost monitor** (56 days stuck):
```bash
oc delete pod cost-data-service-ff95db4b6-8sdkk -n cost-monitor
# If it recreates and sticks in ContainerCreating again, check PVC and secret mounts
oc describe pod <new-pod> -n cost-monitor
```

**OCP portal OAuth** (38 days ImagePullBackOff):
```bash
# Update to current oauth-proxy image tag
oc set image deployment/op-which \
  oauth-proxy=quay.io/openshift/oauth-proxy:v4.17 \
  -n ocp-portal
```

**VM scheduling** (insufficient memory):
```bash
# Check which VMs are pending
oc get pods -n icinga -o wide | grep Pending
# Either increase worker node memory or reduce VM resource requests
```

**Owner**: Infra team
**Time**: 1 hour total
**Risk**: Low

## Priority Order

| Priority | Action | Impact | Time |
|---|---|---|---|
| **P0** | Fix Icinga credentials (#1) | Restores all monitoring alerts | 30min |
| **P0** | Fix Babylon backup disk (#2) | Restores CRD backups | 15min |
| **P0** | Fix sandbox backup SSH key (#3) | Restores config backups | 15min |
| **P1** | Clean Ceph failed pods (#4) | Reduces API server load | 5min/cluster |
| **P1** | Reduce Prometheus CPU (#6) | Frees 10-24 cores per cluster | 30min |
| **P1** | Reduce Splunk CPU (#7) | Frees 7-10 cores per cluster | 1hr |
| **P1** | Capacity gate for ocp4-cluster (#11) | Prevents future CPU saturation | 1-4hr |
| **P2** | Diagnose Ceph cleanup root cause (#5) | Stops storage leak | 2-4hr |
| **P2** | Fix CNV image importers (#8) | Restores image pipeline | 1-2hr |
| **P2** | Fix installation-iso contention (#9) | Speeds up provisioning | 2-4hr |
| **P2** | Fix broken showroom labs (#10) | 17 users restored | 30min/lab |
| **P3** | Upgrade secret-generator (#12) | Fixes 5 clusters | 30min |
| **P3** | Fix infra01 issues (#13) | Cost monitor, portal, VMs | 1hr |
