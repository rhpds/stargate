"""Multi-cluster K8s event mining — collect, classify, and build failure corpus.

Scrapes K8s warning events from multiple clusters, classifies them into
failure patterns, and stores as ground truth for StarGate's learning system.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.k8s_miner")

SECRETS_DIR = Path(__file__).parent.parent / "secrets"

K8S_FAILURE_CLASSES = {
    "image_pull_backoff": {
        "pattern": r"(Back-off pulling image|ErrImagePull|ImagePullBackOff|Failed to pull image)",
        "severity": "high",
        "remediation": [
            "Verify the image exists in the registry",
            "Check image pull secrets in the namespace",
            "Verify network connectivity to the registry",
            "oc get events -n {namespace} | grep -i pull",
        ],
    },
    "pods_crashlooping": {
        "pattern": r"(Back-off restarting failed container|CrashLoopBackOff)",
        "severity": "high",
        "remediation": [
            "Check container logs: oc logs -p {pod} -n {namespace}",
            "Review container exit code and resource limits",
            "Verify required ConfigMaps and Secrets exist",
        ],
    },
    "vm_migration_backoff": {
        "pattern": r"(MigrationBackoff|backoff migrating vmi|migrationTargetPodUnschedulable|FailedMigration)",
        "severity": "medium",
        "remediation": [
            "Check target node resource availability",
            "Verify live migration is supported on target node",
            "Check network connectivity between nodes",
            "oc get vmi -n {namespace} -o yaml | grep -A10 migrationState",
        ],
    },
    "hpa_metric_failure": {
        "pattern": r"(FailedGetResourceMetric|failed to get.*utilization|missing request for cpu)",
        "severity": "low",
        "remediation": [
            "Add CPU/memory requests to the container spec",
            "Verify metrics-server is running",
            "Check HPA target reference matches the deployment",
        ],
    },
    "readiness_probe_failed": {
        "pattern": r"(Readiness probe failed|Liveness probe failed|Unhealthy)",
        "severity": "medium",
        "remediation": [
            "Check application startup time vs probe initialDelaySeconds",
            "Verify the health endpoint is responding",
            "Check container port configuration matches probe port",
        ],
    },
    "oom_killed": {
        "pattern": r"(OOMKill|OOM|out of memory|exit code 137)",
        "severity": "high",
        "remediation": [
            "Increase memory limits in the deployment spec",
            "Review application memory usage patterns",
            "Check for memory leaks in the application",
        ],
    },
    "node_pressure": {
        "pattern": r"(NodeNotReady|EvictionThresholdMet|DiskPressure|MemoryPressure|PIDPressure)",
        "severity": "critical",
        "remediation": [
            "Check node conditions: oc get nodes -o wide",
            "Identify top resource consumers: oc adm top pods -A",
            "Consider draining the node and investigating",
        ],
    },
    "pvc_binding_failed": {
        "pattern": r"(FailedBinding|ProvisioningFailed|no persistent volumes available|WaitForFirstConsumer)",
        "severity": "high",
        "remediation": [
            "Check available PVs: oc get pv",
            "Verify storage class exists and has capacity",
            "Check CSI driver health",
        ],
    },
    "quota_exceeded": {
        "pattern": r"(forbidden.*quota|exceeded quota|ResourceQuota)",
        "severity": "medium",
        "remediation": [
            "Check namespace quotas: oc get resourcequota -n {namespace}",
            "Request quota increase or clean up unused resources",
        ],
    },
    "dns_resolution_failed": {
        "pattern": r"(dns.*resolution|nslookup.*failed|could not resolve)",
        "severity": "high",
        "remediation": [
            "Check CoreDNS pods: oc get pods -n openshift-dns",
            "Verify DNS service is running",
            "Test DNS from within a pod",
        ],
    },
    "certificate_error": {
        "pattern": r"(certificate.*expired|x509.*certificate|TLS.*handshake|cert-manager)",
        "severity": "high",
        "remediation": [
            "Check certificate expiry dates",
            "Verify cert-manager is running and can issue certificates",
            "Renew expired certificates",
        ],
    },
    "scheduling_failed": {
        "pattern": r"(FailedScheduling|Unschedulable|insufficient.*resources|nodes are available)",
        "severity": "high",
        "remediation": [
            "Check node resource availability: oc adm top nodes",
            "Verify node selectors and tolerations",
            "Consider scaling the cluster or freeing resources",
        ],
    },
    "claim_misbound": {
        "pattern": r"(ClaimMisbound|claim is bound to a non-existent|pvc.*misbound)",
        "severity": "high",
        "remediation": [
            "Delete the misbound PVC and recreate it",
            "Check if the PV was manually deleted",
            "oc get pvc -n {namespace} -o yaml | grep volumeName",
        ],
    },
    "volume_attach_failed": {
        "pattern": r"(FailedAttachVolume|AttachVolume.*failed|Multi-Attach error)",
        "severity": "high",
        "remediation": [
            "Check if the volume is still attached to another node",
            "Force detach the volume if the previous node is down",
            "oc describe pv {pv_name}",
            "Verify the CSI driver is healthy",
        ],
    },
    "volume_mount_failed": {
        "pattern": r"(FailedMount|MountVolume.*failed|Unable to attach or mount)",
        "severity": "high",
        "remediation": [
            "Check volume and mount path configuration",
            "Verify the Secret or ConfigMap referenced in the volume exists",
            "oc describe pod {pod} -n {namespace} | grep -A5 Volumes",
        ],
    },
    "invalid_configuration": {
        "pattern": r"(InvalidConfiguration|invalid.*config|configuration.*error)",
        "severity": "medium",
        "remediation": [
            "Review the resource configuration for syntax errors",
            "Check CRD validation rules",
            "oc get events -n {namespace} --field-selector=reason=InvalidConfiguration",
        ],
    },
    "deprecated_api": {
        "pattern": r"(deprecatedAnnotation|deprecated.*API|deprecated.*version)",
        "severity": "low",
        "remediation": [
            "Update resource to use the current API version",
            "Check deprecation warnings in oc logs",
            "No immediate action needed — will break on future upgrades",
        ],
    },
    "sync_failed": {
        "pattern": r"(SyncFailed|reconcil.*failed|ReconcileFailed)",
        "severity": "medium",
        "remediation": [
            "Check operator logs for the failing controller",
            "Verify the operand configuration is valid",
            "oc logs deployment/{operator} -n {namespace}",
        ],
    },
    "image_pull_secret_missing": {
        "pattern": r"(FailedToRetrieveImagePullSecret|pull secret.*not found|imagePullSecrets)",
        "severity": "high",
        "remediation": [
            "Create or link the image pull secret in the namespace",
            "oc create secret docker-registry {name} --docker-server=REGISTRY --docker-username=USER --docker-password=TOKEN",
            "oc secrets link default {name} --for=pull",
        ],
    },
    "backoff_limit_exceeded": {
        "pattern": r"(BackoffLimitExceeded|Job has reached the specified backoff limit)",
        "severity": "high",
        "remediation": [
            "Check job pod logs for the failure reason",
            "Increase backoff limit if the failure is transient",
            "Fix the underlying job configuration",
            "oc logs job/{job} -n {namespace}",
        ],
    },
    "volume_resize_failed": {
        "pattern": r"(VolumeResizeFailed|failed to resize|expand.*volume)",
        "severity": "medium",
        "remediation": [
            "Check if the storage class supports volume expansion",
            "Verify available storage capacity",
            "oc get sc {storageclass} -o yaml | grep allowVolumeExpansion",
        ],
    },
    "resolution_failed": {
        "pattern": r"(ResolutionFailed|failed to resolve|OLM.*resolution)",
        "severity": "medium",
        "remediation": [
            "Check operator catalog source health",
            "Verify the operator subscription channel exists",
            "oc get catalogsource -n openshift-marketplace",
        ],
    },
    "datasource_unrecognized": {
        "pattern": r"(UnrecognizedDataSourceKind|unrecognized.*datasource|unknown.*source)",
        "severity": "medium",
        "remediation": [
            "Check if the CDI (Containerized Data Importer) operator is installed",
            "Verify DataVolume source type is supported",
            "oc get crd | grep datavolumes",
        ],
    },
    "pod_pending": {
        "pattern": r"(Pending|pod.*pending|awaiting.*scheduling)",
        "severity": "medium",
        "remediation": [
            "Check if resource requests exceed available node capacity",
            "Verify node affinity and taints/tolerations",
            "oc describe pod {pod} -n {namespace} | grep -A10 Events",
        ],
    },
}


def parse_k8s_event(raw: Dict) -> Dict:
    """Parse and classify a single K8s event."""
    event_type = raw.get("type", "Normal")
    reason = raw.get("reason", "")
    message = raw.get("message", "")
    combined = f"{reason} {message}"

    failure_class = "unclassified"
    severity = "low"
    remediation = []

    for cls_name, cls_data in K8S_FAILURE_CLASSES.items():
        if re.search(cls_data["pattern"], combined, re.IGNORECASE):
            failure_class = cls_name
            severity = cls_data["severity"]
            remediation = cls_data["remediation"]
            break

    return {
        "failure_class": failure_class,
        "severity": severity,
        "type": event_type,
        "reason": reason,
        "message": message[:300],
        "namespace": raw.get("namespace", ""),
        "resource_kind": raw.get("resource_kind", ""),
        "resource_name": raw.get("resource_name", ""),
        "cluster": raw.get("cluster", ""),
        "count": raw.get("count", 1),
        "remediation": remediation,
        "source": "k8s_events",
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }


def mine_cluster_events(cluster_name: str, kubeconfig: str, limit: int = 500) -> List[Dict]:
    """Scrape warning events from a single cluster."""
    kc = str(SECRETS_DIR / kubeconfig)
    if not os.path.exists(kc):
        logger.warning("Kubeconfig not found: %s", kc)
        return []

    try:
        result = subprocess.run(
            ["oc", "--kubeconfig", kc, "get", "events", "-A", "--no-headers",
             "--field-selector", "type=Warning", "--sort-by", ".lastTimestamp"],
            capture_output=True, text=True, timeout=30,
        )
        events = []
        for line in result.stdout.strip().split("\n")[-limit:]:
            if not line.strip():
                continue
            parts = line.split(None, 5)
            if len(parts) >= 6:
                ns = parts[0]
                reason = parts[3] if len(parts) > 3 else ""
                kind_name = parts[4] if len(parts) > 4 else ""
                message = parts[5] if len(parts) > 5 else ""
                resource_kind, resource_name = "", ""
                if "/" in kind_name:
                    resource_kind, resource_name = kind_name.split("/", 1)

                events.append({
                    "type": "Warning",
                    "reason": reason,
                    "message": message[:500],
                    "namespace": ns,
                    "resource_kind": resource_kind,
                    "resource_name": resource_name,
                    "cluster": cluster_name,
                })
        return events
    except Exception as e:
        logger.warning("Failed to mine events from %s: %s", cluster_name, e)
        return []


def mine_all_clusters(clusters: Optional[Dict[str, str]] = None, limit_per_cluster: int = 200) -> List[Dict]:
    """Mine events from all configured clusters."""
    if clusters is None:
        from cli.scan import load_clusters
        clusters = load_clusters()

    all_events = []
    for name, kc in clusters.items():
        events = mine_cluster_events(name, kc, limit=limit_per_cluster)
        all_events.extend(events)
        logger.info("Mined %d events from %s", len(events), name)

    return all_events


def batch_classify_events(events: List[Dict], db=None) -> Dict:
    """Classify a batch of K8s events and optionally persist."""
    results = []
    classified = 0

    for raw in events:
        parsed = parse_k8s_event(raw)
        results.append(parsed)
        if parsed["failure_class"] != "unclassified":
            classified += 1

    if db:
        try:
            from db import repository
            for parsed in results:
                if parsed["failure_class"] == "unclassified":
                    continue
                repository.create_evaluation(
                    db, run_id=f"k8s-mine-{parsed['cluster']}-{parsed['resource_name'][:20]}",
                    stage_id="cluster-health", outcome="fail",
                    failure_class=parsed["failure_class"],
                    message=parsed["message"][:200],
                    criteria_results=[], lab_code=parsed["namespace"],
                    cluster_name=parsed["cluster"],
                )
        except Exception as e:
            logger.warning("Failed to persist mined events: %s", e)

    counts: Dict[str, int] = {}
    for r in results:
        fc = r["failure_class"]
        counts[fc] = counts.get(fc, 0) + 1

    return {
        "total": len(events),
        "classified": classified,
        "unclassified": len(events) - classified,
        "by_class": counts,
        "by_cluster": _count_by_cluster(results),
    }


def _count_by_cluster(results: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in results:
        c = r["cluster"]
        counts[c] = counts.get(c, 0) + 1
    return counts
