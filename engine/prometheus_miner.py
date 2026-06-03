"""Prometheus metrics mining — collect failure signals from cluster metrics.

Queries Prometheus/Thanos on each cluster for health indicators:
pod restart rates, OOM kills, CPU saturation, PVC fill levels, etc.
Cross-references with K8s events and alerts for predictive patterns.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.prometheus")

SECRETS_DIR = Path(__file__).parent.parent / "secrets"

HEALTH_QUERIES = {
    "pod_restarts": {
        "query": "sort_desc(kube_pod_container_status_restarts_total>10)",
        "failure_class": "pod_high_restart_rate",
        "severity": "warning",
        "description": "Pod has restarted more than 10 times",
    },
    "oom_kills": {
        "query": "increase(kube_pod_container_status_last_terminated_reason{reason='OOMKilled'}[7d])>0",
        "failure_class": "container_oom_killed",
        "severity": "high",
        "description": "Container was OOM killed in the last 7 days",
    },
    "cpu_saturation": {
        "query": "instance:node_cpu_utilisation:rate5m>0.8",
        "failure_class": "node_cpu_saturated",
        "severity": "warning",
        "description": "Node CPU utilization exceeds 80%",
    },
    "pvc_filling": {
        "query": "(kubelet_volume_stats_used_bytes/kubelet_volume_stats_capacity_bytes)>0.85",
        "failure_class": "pvc_nearly_full",
        "severity": "warning",
        "description": "PVC usage exceeds 85%",
    },
    "node_memory": {
        "query": "(1-node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)>0.9",
        "failure_class": "node_memory_exhausted",
        "severity": "critical",
        "description": "Node memory usage exceeds 90%",
    },
    "api_latency": {
        "query": "histogram_quantile(0.99,rate(apiserver_request_duration_seconds_bucket{verb!='WATCH'}[5m]))>1",
        "failure_class": "api_server_slow",
        "severity": "warning",
        "description": "API server p99 latency exceeds 1 second",
    },
    "etcd_latency": {
        "query": "histogram_quantile(0.99,rate(etcd_disk_backend_commit_duration_seconds_bucket[5m]))>0.1",
        "failure_class": "etcd_slow_commits",
        "severity": "warning",
        "description": "etcd p99 commit latency exceeds 100ms",
    },
    "pending_pods": {
        "query": "kube_pod_status_phase{phase='Pending'}>0",
        "failure_class": "pod_stuck_pending",
        "severity": "medium",
        "description": "Pod stuck in Pending phase",
    },
}


def _get_thanos_url(cluster_name: str) -> str:
    """Get the Thanos URL for a cluster."""
    cluster_urls = {
        "ocpv-infra01": "https://thanos-querier-openshift-monitoring.apps.ocpv-infra01.dal12.infra.demo.redhat.com",
        "ocpv-infra02": "https://thanos-querier-openshift-monitoring.apps.ocpv-infra02.wdc07.infra.demo.redhat.com",
        "ocpv05": "https://thanos-querier-openshift-monitoring.apps.ocpv05.dal10.infra.demo.redhat.com",
        "ocpv07": "https://thanos-querier-openshift-monitoring.apps.ocpv07.wdc06.infra.demo.redhat.com",
        "ocpv08": "https://thanos-querier-openshift-monitoring.apps.ocpv08.dal10.infra.demo.redhat.com",
        "ocpv09": "https://thanos-querier-openshift-monitoring.apps.ocpv09.dal13.infra.demo.redhat.com",
    }
    return cluster_urls.get(cluster_name, "")


def _get_token(cluster_name: str) -> str:
    """Get auth token for a cluster — from kubeconfig or env."""
    kc_map = {
        "ocpv-infra01": "kubeconfig-infra01",
        "ocpv-infra02": "kubeconfig-infra02",
        "ocpv05": "kubeconfig-ocpv05",
        "ocpv07": "kubeconfig-ocpv07",
        "ocpv08": "kubeconfig-ocpv08",
        "ocpv09": "kubeconfig-ocpv09",
    }
    kc_file = SECRETS_DIR / kc_map.get(cluster_name, "")
    if kc_file.exists():
        with open(kc_file) as f:
            for line in f:
                if "token:" in line:
                    return line.split("token:", 1)[1].strip()
    return ""


def query_prometheus(cluster_name: str, promql: str) -> List[Dict]:
    """Execute a PromQL query against a cluster's Thanos endpoint."""
    url = _get_thanos_url(cluster_name)
    token = _get_token(cluster_name)
    if not url or not token:
        return []

    try:
        ctx = ssl.create_default_context()
        if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        encoded = urllib.request.quote(promql, safe="")
        req = urllib.request.Request(
            f"{url}/api/v1/query?query={encoded}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        data = json.loads(resp.read())
        if data.get("status") == "success":
            return data.get("data", {}).get("result", [])
    except Exception as e:
        logger.debug("Prometheus query failed on %s: %s", cluster_name, e)
    return []


def parse_metric_result(raw: Dict, query_name: str, cluster: str) -> Dict:
    """Parse a single Prometheus result into our classified format."""
    q = HEALTH_QUERIES.get(query_name, {})
    metric = raw.get("metric", {})
    value = float(raw.get("value", [0, 0])[1])

    return {
        "failure_class": q.get("failure_class", "unknown_metric"),
        "severity": q.get("severity", "medium"),
        "description": q.get("description", ""),
        "namespace": metric.get("namespace", ""),
        "pod": metric.get("pod", ""),
        "container": metric.get("container", ""),
        "node": metric.get("instance", metric.get("node", "")),
        "cluster": cluster,
        "value": value,
        "query_name": query_name,
        "source": "prometheus",
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }


def mine_cluster_metrics(cluster_name: str) -> List[Dict]:
    """Run all health queries against a single cluster."""
    results = []
    for query_name, q in HEALTH_QUERIES.items():
        raw_results = query_prometheus(cluster_name, q["query"])
        for raw in raw_results:
            parsed = parse_metric_result(raw, query_name, cluster_name)
            results.append(parsed)
    return results


def mine_all_clusters(clusters: Optional[List[str]] = None) -> List[Dict]:
    """Mine metrics from all configured clusters."""
    if clusters is None:
        clusters = ["ocpv-infra01", "ocpv-infra02", "ocpv05", "ocpv07", "ocpv08", "ocpv09"]

    all_results = []
    for cluster in clusters:
        metrics = mine_cluster_metrics(cluster)
        all_results.extend(metrics)
        if metrics:
            logger.info("Mined %d metric findings from %s", len(metrics), cluster)
    return all_results


def batch_classify_metrics(metrics: List[Dict]) -> Dict:
    """Summarize classified metrics."""
    counts: Dict[str, int] = {}
    for m in metrics:
        fc = m.get("failure_class", "unknown")
        counts[fc] = counts.get(fc, 0) + 1

    return {
        "total": len(metrics),
        "classified": len(metrics),
        "by_class": counts,
        "by_cluster": {c: sum(1 for m in metrics if m["cluster"] == c) for c in set(m["cluster"] for m in metrics)} if metrics else {},
    }
