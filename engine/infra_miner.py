"""Infrastructure miner — collects Ceph health, operator status, ingress errors, node health.

Gathers infrastructure-level signals that are root causes behind
higher-level failures (pod crashes, scheduling failures, PVC issues).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from engine.failure_class_loader import classify_by_pattern

logger = logging.getLogger("stargate.infra_miner")

SECRETS_DIR = Path(__file__).parent.parent / "secrets"


def _run_oc(args: List[str], kubeconfig: str, timeout: int = 15) -> str:
    kc = str(SECRETS_DIR / kubeconfig)
    if not os.path.exists(kc):
        return ""
    try:
        result = subprocess.run(
            ["oc", f"--kubeconfig={kc}"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def mine_ceph_health(cluster: str, kubeconfig: str) -> List[Dict]:
    """Check Ceph/ODF storage health."""
    findings = []
    raw = _run_oc(["get", "cephcluster", "-n", "openshift-storage", "-o", "json"], kubeconfig)
    if not raw:
        return findings
    try:
        data = json.loads(raw)
        items = data.get("items", [data]) if data.get("kind") != "CephClusterList" else data.get("items", [])
        for item in items:
            health = item.get("status", {}).get("ceph", {}).get("health", "")
            if health != "HEALTH_OK":
                fc, matched = classify_by_pattern(health, "infrastructure")
                findings.append({
                    "failure_class": fc if fc != "unclassified" else "ceph_health_warning",
                    "severity": "critical" if "ERR" in health else "warning",
                    "description": f"Ceph cluster health: {health}",
                    "cluster": cluster,
                    "namespace": "openshift-storage",
                    "source": "ceph",
                    "classified_at": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as e:
        logger.debug("Ceph parse failed: %s", e)
    return findings


def mine_operator_health(cluster: str, kubeconfig: str) -> List[Dict]:
    """Check cluster operator status."""
    findings = []
    raw = _run_oc(["get", "co", "-o", "json"], kubeconfig)
    if not raw:
        return findings
    try:
        data = json.loads(raw)
        for op in data.get("items", []):
            name = op.get("metadata", {}).get("name", "")
            conditions = {c["type"]: c for c in op.get("status", {}).get("conditions", [])}
            degraded = conditions.get("Degraded", {})
            available = conditions.get("Available", {})
            if degraded.get("status") == "True" or available.get("status") == "False":
                msg = degraded.get("message", available.get("message", ""))
                findings.append({
                    "failure_class": "operator_degraded",
                    "severity": "high",
                    "description": f"Operator {name} degraded: {msg[:200]}",
                    "resource_name": name,
                    "cluster": cluster,
                    "namespace": "openshift-*",
                    "source": "cluster_operators",
                    "classified_at": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as e:
        logger.debug("Operator parse failed: %s", e)
    return findings


def mine_node_conditions(cluster: str, kubeconfig: str) -> List[Dict]:
    """Check node conditions for pressure/not-ready."""
    findings = []
    raw = _run_oc(["get", "nodes", "-o", "json"], kubeconfig)
    if not raw:
        return findings
    try:
        data = json.loads(raw)
        for node in data.get("items", []):
            name = node.get("metadata", {}).get("name", "")
            for cond in node.get("status", {}).get("conditions", []):
                if cond["type"] == "Ready" and cond["status"] != "True":
                    findings.append({
                        "failure_class": "node_not_ready",
                        "severity": "critical",
                        "description": f"Node {name} not ready: {cond.get('reason', '')}",
                        "resource_name": name,
                        "cluster": cluster,
                        "source": "node_conditions",
                        "classified_at": datetime.now(timezone.utc).isoformat(),
                    })
                elif cond["type"] in ("DiskPressure", "MemoryPressure", "PIDPressure") and cond["status"] == "True":
                    fc, _ = classify_by_pattern(cond["type"], "infrastructure")
                    findings.append({
                        "failure_class": fc if fc != "unclassified" else "node_pressure",
                        "severity": "critical",
                        "description": f"Node {name}: {cond['type']}",
                        "resource_name": name,
                        "cluster": cluster,
                        "source": "node_conditions",
                        "classified_at": datetime.now(timezone.utc).isoformat(),
                    })
    except Exception as e:
        logger.debug("Node parse failed: %s", e)
    return findings


def mine_cluster_infra(cluster: str, kubeconfig: str) -> List[Dict]:
    """Run all infrastructure checks on a single cluster."""
    findings = []
    findings.extend(mine_ceph_health(cluster, kubeconfig))
    findings.extend(mine_operator_health(cluster, kubeconfig))
    findings.extend(mine_node_conditions(cluster, kubeconfig))
    return findings


def mine_all_clusters(clusters: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Mine infrastructure health from all configured clusters."""
    if clusters is None:
        from cli.scan import load_clusters
        clusters = load_clusters()

    all_findings = []
    for name, kc in clusters.items():
        findings = mine_cluster_infra(name, kc)
        all_findings.extend(findings)
        if findings:
            logger.info("Found %d infra issues on %s", len(findings), name)
        else:
            logger.info("%s: infrastructure healthy", name)
    return all_findings
