"""Alertmanager alert mining — collect and classify OpenShift alerts.

Alerts are pre-classified by Prometheus rules. We map alertnames to our
failure classes and add remediation guidance. This is the richest "free"
data source — every alert is a labeled incident with severity and timestamps.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.alertmanager")

ALERT_FAILURE_CLASSES = {
    "node_memory_pressure": {
        "alertnames": ["SystemMemoryExceedsReservation", "NodeMemoryPressure", "KubeMemoryOvercommit"],
        "severity": "warning",
        "remediation": [
            "Check memory usage per node: oc adm top nodes",
            "Identify top memory consumers: oc adm top pods -A --sort-by=memory",
            "Consider evicting non-critical workloads or adding nodes",
            "Review system reserved memory configuration",
        ],
    },
    "pdb_at_limit": {
        "alertnames": ["PodDisruptionBudgetAtLimit", "PodDisruptionBudgetLimit"],
        "severity": "warning",
        "remediation": [
            "Check which PDBs are at limit: oc get pdb -A",
            "Review if the PDB minAvailable is too high",
            "May block node drains and upgrades",
        ],
    },
    "insights_cve": {
        "alertnames": ["InsightsRecommendationActive"],
        "pattern": r"CVE-\d{4}-\d+",
        "severity": "info",
        "remediation": [
            "Review the CVE in Red Hat Security Advisories",
            "Check if an errata is available",
            "Plan patching window if severity is high/critical",
            "Monitor Insights dashboard for mitigation guidance",
        ],
    },
    "insights_recommendation": {
        "alertnames": ["InsightsRecommendationActive"],
        "severity": "info",
        "remediation": [
            "Review recommendation in OpenShift Insights dashboard",
            "Evaluate impact and plan implementation",
        ],
    },
    "monitoring_target_down": {
        "alertnames": ["TargetDown"],
        "severity": "warning",
        "remediation": [
            "Check which targets are down: oc get endpoints -n openshift-monitoring",
            "Verify the monitored service is running",
            "Check network policies blocking scrape endpoints",
        ],
    },
    "cluster_not_upgradeable": {
        "alertnames": ["ClusterNotUpgradeable"],
        "severity": "warning",
        "remediation": [
            "Check cluster operator status: oc get co",
            "Identify blocking conditions: oc get clusterversion -o yaml",
            "Resolve operator issues before attempting upgrade",
        ],
    },
    "alertmanager_misconfigured": {
        "alertnames": ["AlertmanagerReceiversNotConfigured", "AlertmanagerFailedReload"],
        "severity": "warning",
        "remediation": [
            "Configure alert receivers (email, Slack, PagerDuty)",
            "Check alertmanager config: oc get secret alertmanager-main -n openshift-monitoring -o yaml",
        ],
    },
    "argocd_sync_failed": {
        "alertnames": ["ArgoCDSyncAlert", "ArgoCDAppSyncFailed"],
        "severity": "warning",
        "remediation": [
            "Check ArgoCD application sync status",
            "Review git diff between desired and live state",
            "Check for resource conflicts or RBAC issues",
            "argocd app get {app_name}",
        ],
    },
    "cdi_storage_incomplete": {
        "alertnames": ["CDIStorageProfilesIncomplete"],
        "severity": "info",
        "remediation": [
            "Check CDI storage profiles: oc get storageprofile",
            "Verify storage class has required annotations for CDI",
        ],
    },
    "outdated_vmi_workloads": {
        "alertnames": ["OutdatedVirtualMachineInstanceWorkloads"],
        "severity": "info",
        "remediation": [
            "Restart VMIs to pick up the latest virt-launcher version",
            "oc get vmi -A | grep -v Running",
            "Schedule rolling restart during maintenance window",
        ],
    },
    "watchdog": {
        "alertnames": ["Watchdog"],
        "severity": "none",
        "remediation": [
            "This is a health-check alert — no action needed",
            "If this alert is NOT firing, alerting pipeline is broken",
        ],
    },
    "etcd_slow": {
        "alertnames": ["etcdHighCommitDurations", "etcdHighFsyncDurations", "etcdDatabaseHighFragmentationRatio"],
        "severity": "warning",
        "remediation": [
            "Check etcd disk performance: oc logs -n openshift-etcd -l app=etcd",
            "Consider defragmenting etcd: etcdctl defrag",
            "Verify storage I/O performance on control plane nodes",
        ],
    },
    "kube_api_errors": {
        "alertnames": ["KubeAPIErrorBudgetBurn", "KubeAPILatencyHigh"],
        "severity": "critical",
        "remediation": [
            "Check API server logs: oc logs -n openshift-kube-apiserver -l app=openshift-kube-apiserver",
            "Review audit logs for high-volume clients",
            "Check etcd health — API latency often caused by slow etcd",
        ],
    },
    "node_not_ready": {
        "alertnames": ["KubeNodeNotReady", "KubeNodeUnreachable"],
        "severity": "critical",
        "remediation": [
            "Check node status: oc get nodes",
            "SSH to the node and check kubelet: systemctl status kubelet",
            "Check for network partition or hardware failure",
        ],
    },
    "persistent_volume_errors": {
        "alertnames": ["KubePersistentVolumeErrors", "KubePersistentVolumeFillingUp"],
        "severity": "warning",
        "remediation": [
            "Check PV status: oc get pv | grep -v Bound",
            "Identify filling volumes: oc get pvc -A --sort-by=.status.capacity.storage",
            "Plan capacity expansion or cleanup",
        ],
    },
}


def parse_alert(alert: Dict, cluster: str = "unknown") -> Dict:
    """Parse and classify a single Alertmanager alert."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    alertname = labels.get("alertname", "")
    severity = labels.get("severity", "info")
    description = annotations.get("description", annotations.get("summary", ""))

    from engine.failure_class_loader import classify_by_alertname
    failure_class, matched = classify_by_alertname(alertname, description)
    if failure_class == "unclassified_alert":
        if alertname == "InsightsRecommendationActive" and re.search(r"CVE-\d{4}-\d+", description):
            failure_class = "insights_cve"
        else:
            for cls_name, cls_data in ALERT_FAILURE_CLASSES.items():
                if alertname in cls_data.get("alertnames", []):
                    failure_class = cls_name
                    break

    cls_data = matched if matched else ALERT_FAILURE_CLASSES.get(failure_class, {})
    return {
        "failure_class": failure_class,
        "alertname": alertname,
        "severity": severity,
        "namespace": labels.get("namespace", ""),
        "node": labels.get("node", labels.get("instance", "")),
        "description": description[:300],
        "starts_at": alert.get("startsAt", ""),
        "cluster": cluster,
        "remediation": cls_data.get("remediation", []),
        "source": "alertmanager",
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_alerts(cluster_name: str = "infra01", alertmanager_url: str = "") -> List[Dict]:
    """Collect alerts from Alertmanager API."""
    if not alertmanager_url:
        alertmanager_url = os.environ.get("ALERTMANAGER_URL", "")
    if not alertmanager_url:
        logger.warning("No ALERTMANAGER_URL configured")
        return []

    token = os.environ.get("OPENSHIFT_TOKEN", "")
    if not token:
        try:
            import subprocess
            token = subprocess.run(["oc", "whoami", "-t"], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass

    if not token:
        logger.warning("No OpenShift token — can't access Alertmanager")
        return []

    try:
        ctx = ssl.create_default_context()
        if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            f"{alertmanager_url}/api/v2/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        alerts = json.loads(resp.read())
        return [{"cluster": cluster_name, **a} for a in alerts]
    except Exception as e:
        logger.warning("Failed to collect alerts from %s: %s", alertmanager_url, e)
        return []


def batch_classify_alerts(alerts: List[Dict], cluster: str = "unknown", db=None) -> Dict:
    """Classify a batch of alerts."""
    results = []
    classified = 0

    for alert in alerts:
        parsed = parse_alert(alert, cluster)
        results.append(parsed)
        if parsed["failure_class"] != "unclassified_alert":
            classified += 1

    if db:
        try:
            from db import repository
            for parsed in results:
                if parsed["failure_class"] == "unclassified_alert":
                    continue
                repository.create_evaluation(
                    db, run_id=f"alert-{parsed['alertname']}-{parsed['cluster']}",
                    stage_id="cluster-health", outcome="fail" if parsed["severity"] in ("critical", "warning") else "warn",
                    failure_class=parsed["failure_class"],
                    message=parsed["description"][:200],
                    criteria_results=[], lab_code=parsed["namespace"],
                    cluster_name=parsed["cluster"],
                )
        except Exception as e:
            logger.warning("Failed to persist alerts: %s", e)

    counts: Dict[str, int] = {}
    for r in results:
        fc = r["failure_class"]
        counts[fc] = counts.get(fc, 0) + 1

    return {
        "total": len(alerts),
        "classified": classified,
        "unclassified": len(alerts) - classified,
        "by_class": counts,
    }
