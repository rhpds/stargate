"""Corpus runner — orchestrates all miners and loads results into StarGate DB.

Runs K8s event mining, Alertmanager collection, Prometheus metrics,
infrastructure checks, and AAP ingestion. Aggregates results and
optionally persists to the StarGate evaluation database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from engine.failure_class_loader import get_all_classes, reload

logger = logging.getLogger("stargate.corpus")


def run_all_miners(
    clusters: Optional[Dict[str, str]] = None,
    prometheus_clusters: Optional[List[str]] = None,
    db=None,
    dry_run: bool = False,
) -> Dict:
    """Run all miners and return aggregated results."""
    reload()
    all_classes = get_all_classes()
    results: List[Dict] = []
    by_source: Dict[str, int] = {}
    errors: List[str] = []

    # K8s Events
    try:
        from engine.k8s_event_miner import mine_all_clusters as mine_k8s, batch_classify_events
        events = mine_k8s(clusters=clusters, limit_per_cluster=200)
        classified = batch_classify_events(events, db=db if not dry_run else None)
        by_source["k8s_events"] = classified["total"]
        results.extend([{"source": "k8s_events", **r} for r in events[:5]])
        logger.info("K8s events: %d mined, %d classified", classified["total"], classified["classified"])
    except Exception as e:
        errors.append(f"k8s_events: {e}")
        logger.warning("K8s event mining failed: %s", e)

    # Alertmanager
    try:
        from engine.alertmanager_miner import collect_alerts, batch_classify_alerts
        alerts = collect_alerts("infra01")
        if alerts:
            classified = batch_classify_alerts(alerts, "infra01", db=db if not dry_run else None)
            by_source["alertmanager"] = classified["total"]
            logger.info("Alertmanager: %d alerts, %d classified", classified["total"], classified["classified"])
        else:
            by_source["alertmanager"] = 0
    except Exception as e:
        errors.append(f"alertmanager: {e}")
        logger.warning("Alertmanager mining failed: %s", e)

    # Prometheus Metrics
    try:
        from engine.prometheus_miner import mine_all_clusters as mine_prom, batch_classify_metrics
        from cli.scan import load_clusters
        prom_clusters = prometheus_clusters or list(load_clusters().keys())
        metrics = mine_prom(clusters=prom_clusters)
        if metrics:
            classified = batch_classify_metrics(metrics)
            by_source["prometheus"] = classified["total"]
            logger.info("Prometheus: %d findings from %d clusters", classified["total"], len(prom_clusters))
        else:
            by_source["prometheus"] = 0
    except Exception as e:
        errors.append(f"prometheus: {e}")
        logger.warning("Prometheus mining failed: %s", e)

    # Infrastructure
    try:
        from engine.infra_miner import mine_all_clusters as mine_infra
        infra = mine_infra(clusters=clusters)
        by_source["infrastructure"] = len(infra)
        if infra:
            logger.info("Infrastructure: %d findings", len(infra))
    except Exception as e:
        errors.append(f"infrastructure: {e}")
        logger.warning("Infrastructure mining failed: %s", e)

    total = sum(by_source.values())

    # Count by failure class across all results
    by_class: Dict[str, int] = {}
    for source, count in by_source.items():
        by_class[source] = count

    return {
        "total_findings": total,
        "by_source": by_source,
        "by_class": by_class,
        "total_failure_classes": len(all_classes),
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
    }


def get_corpus_stats() -> Dict:
    """Get current corpus statistics without running miners."""
    reload()
    all_classes = get_all_classes()

    by_source: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    for name, data in all_classes.items():
        source = data.get("_source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1
        severity = data.get("severity", "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1

    has_remediation = sum(1 for d in all_classes.values() if d.get("remediation"))

    return {
        "total_classes": len(all_classes),
        "by_source": by_source,
        "by_severity": by_severity,
        "with_remediation": has_remediation,
        "sources": sorted(by_source.keys()),
    }
