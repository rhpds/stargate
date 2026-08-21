"""Dashboard sub-router — pools, provisioning, trends, nodes, pipeline."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.routers._shared import (
    _load_latest_scan,
    _load_latest_babylon,
    _scan_to_worker_format,
    PIPELINE_STAGES,
)

router = APIRouter()
logger = logging.getLogger("stargate.dashboard.infra")


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------

@router.get("/dashboard/pools")
def dashboard_pools():
    """Pool capacity and provisioning state from Babylon cache — all pools."""
    babylon = _load_latest_babylon()
    pools_data = babylon.get("pools", {})
    prov = babylon.get("provisioning", {})

    exhausted_names = {p.get("name") for p in pools_data.get("exhausted", []) if isinstance(p, dict)}
    low_names = {p.get("name") for p in pools_data.get("low", []) if isinstance(p, dict)}

    all_pools_raw = pools_data.get("all_pools", pools_data.get("summit_pools", []))

    pool_list = []
    for p in all_pools_raw:
        if not isinstance(p, dict):
            continue
        name = p.get("name", "")
        if not name:
            continue
        avail = p.get("available", 0)
        mn = p.get("min", 0)
        if name in exhausted_names or (avail == 0 and mn > 0):
            status = "exhausted"
        elif name in low_names or (avail <= 1 and mn > 0):
            status = "low"
        else:
            status = "healthy"
        pool_list.append({
            "name": name,
            "available": avail,
            "ready": p.get("ready", 0),
            "min": mn,
            "status": status,
            "is_summit": p.get("is_summit", "summit-2026" in name),
        })

    instance_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))
    labs_by_pool: Dict[str, set] = {}
    for lc, instances in instance_mapping.items():
        for inst in instances:
            pool_name = inst.get("pool_name", "")
            if pool_name:
                labs_by_pool.setdefault(pool_name, set()).add(lc)

    for pool in pool_list:
        consuming = labs_by_pool.get(pool["name"], set())
        pool["consuming_labs"] = sorted(consuming)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_pools": pools_data.get("total_pools", len(pool_list)),
        "pools": pool_list,
        "summit_pools": pool_list,
        "provisioning": {
            "total": prov.get("total", 0),
            "started": prov.get("started", 0),
            "failed": prov.get("failed", 0),
            "failure_rate": prov.get("failure_rate", 0),
            "by_state": prov.get("by_state", {}),
        },
    }


# ---------------------------------------------------------------------------
# Pool / Provisioning / Catalog Detail
# ---------------------------------------------------------------------------

@router.get("/dashboard/pool/{pool_name}")
def dashboard_pool_detail(pool_name: str):
    """Single pool deep-dive — capacity, consuming labs, instance breakdown."""
    babylon = _load_latest_babylon()
    pools_data = babylon.get("pools", {})
    all_pools = pools_data.get("all_pools", pools_data.get("summit_pools", []))

    pool = None
    for p in all_pools:
        if isinstance(p, dict) and p.get("name") == pool_name:
            pool = p
            break
    if not pool:
        raise HTTPException(status_code=404, detail=f"Pool '{pool_name}' not found")

    avail = pool.get("available", 0)
    mn = pool.get("min", 0)
    exhausted_names = {ep.get("name") for ep in pools_data.get("exhausted", []) if isinstance(ep, dict)}
    low_names = {ep.get("name") for ep in pools_data.get("low", []) if isinstance(ep, dict)}
    if pool_name in exhausted_names or (avail == 0 and mn > 0):
        status = "exhausted"
    elif pool_name in low_names or (avail <= 1 and mn > 0):
        status = "low"
    else:
        status = "healthy"

    instance_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))
    instances = []
    consuming_labs: set = set()
    by_state: Dict[str, int] = {}
    pool_slug = pool_name.split(".")[1] if "." in pool_name else pool_name
    for lc, insts in instance_mapping.items():
        for inst in insts:
            matches = inst.get("pool_name", "") == pool_name or pool_slug in inst.get("anarchy_name", "")
            if matches:
                instances.append({**inst, "lab_code": lc})
                consuming_labs.add(lc)
                st = inst.get("state", "unknown")
                by_state[st] = by_state.get(st, 0) + 1

    return {
        "name": pool_name,
        "available": avail,
        "ready": pool.get("ready", 0),
        "min": mn,
        "status": status,
        "is_summit": pool.get("is_summit", "summit-2026" in pool_name),
        "consuming_labs": sorted(consuming_labs),
        "instances": instances[:200],
        "instance_summary": {"total": len(instances), "by_state": by_state},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/dashboard/provisioning")
def dashboard_provisioning():
    """Provisioning overview — all AnarchySubjects grouped by state."""
    babylon = _load_latest_babylon()
    prov = babylon.get("provisioning", {})
    instance_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))

    subjects_by_state: Dict[str, list] = {}
    labs_affected: Dict[str, Dict] = {}
    for lc, insts in instance_mapping.items():
        lab_total = 0
        lab_started = 0
        lab_failed = 0
        for inst in insts:
            st = inst.get("state", "unknown")
            lab_total += 1
            if st == "started":
                lab_started += 1
            if "failed" in st or "error" in st:
                lab_failed += 1
            if st not in subjects_by_state:
                subjects_by_state[st] = []
            if st != "started" or len(subjects_by_state[st]) < 50:
                subjects_by_state[st].append({**inst, "lab_code": lc})
        if lab_total > 0:
            labs_affected[lc] = {"total": lab_total, "started": lab_started, "failed": lab_failed}

    return {
        "total": prov.get("total", 0),
        "started": prov.get("started", 0),
        "failed": prov.get("failed", 0),
        "failure_rate": prov.get("failure_rate", 0),
        "by_state": prov.get("by_state", {}),
        "subjects_by_state": subjects_by_state,
        "labs_affected": labs_affected,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/dashboard/catalog/{item_name}")
def dashboard_catalog_detail(item_name: str):
    """Single catalog item detail — linked pools, instances, sessions."""
    babylon = _load_latest_babylon()
    catalog_items = babylon.get("catalog_items", [])

    item = None
    for ci in catalog_items:
        if isinstance(ci, dict) and ci.get("name") == item_name:
            item = ci
            break
    if not item:
        raise HTTPException(status_code=404, detail=f"Catalog item '{item_name}' not found")

    slug = item_name.split(".", 1)[1] if "." in item_name else item_name
    pools_data = babylon.get("pools", {})
    all_pools = pools_data.get("all_pools", pools_data.get("summit_pools", []))
    linked_pools = [
        {"name": p["name"], "available": p.get("available", 0), "ready": p.get("ready", 0), "min": p.get("min", 0)}
        for p in all_pools if isinstance(p, dict) and slug in p.get("name", "")
    ]

    lab_code = item.get("lab_code", "")
    instance_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))
    instances = instance_mapping.get(lab_code, []) if lab_code else []
    by_state: Dict[str, int] = {}
    for inst in instances:
        st = inst.get("state", "unknown")
        by_state[st] = by_state.get(st, 0) + 1

    return {
        **item,
        "linked_pools": linked_pools,
        "instances": instances[:100],
        "instance_summary": {"total": len(instances), "by_state": by_state},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Historical Trend Endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboard/aap-trends")
def dashboard_aap_trends(hours: int = 24, db: Session = Depends(get_db)):
    """AAP provisioning SLI timeline."""
    return {"timeline": repository.get_aap_timeline(db, hours=hours)}


@router.get("/dashboard/provisioning-trends")
def dashboard_provisioning_trends(hours: int = 24, db: Session = Depends(get_db)):
    """Provisioning state timeline (AnarchySubject totals over time)."""
    return {"timeline": repository.get_provisioning_timeline(db, hours=hours)}


@router.get("/dashboard/sandbox-trends")
def dashboard_sandbox_trends(hours: int = 24, db: Session = Depends(get_db)):
    """Sandbox API health and queue depth timeline."""
    return {"timeline": repository.get_sandbox_timeline(db, hours=hours)}


@router.get("/dashboard/mttr")
def dashboard_mttr(hours: int = 168, db: Session = Depends(get_db)):
    """Mean time to recovery computed from evaluation pass/fail transitions."""
    return repository.compute_mttr(db, hours=hours)


@router.get("/dashboard/resolutions")
def dashboard_resolutions(
    lab_code: Optional[str] = None,
    failure_class: Optional[str] = None,
    hours: int = 168,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Recent resolution records with cause attribution."""
    from db.models import ResolutionRecord

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = db.query(ResolutionRecord).filter(ResolutionRecord.resolved_at >= cutoff)
    if lab_code:
        query = query.filter(ResolutionRecord.lab_code == lab_code)
    if failure_class:
        query = query.filter(ResolutionRecord.failure_class == failure_class)

    records = query.order_by(ResolutionRecord.resolved_at.desc()).limit(limit).all()

    by_type: Dict[str, int] = {}
    ttr_values: List[float] = []
    for r in records:
        by_type[r.resolution_type] = by_type.get(r.resolution_type, 0) + 1
        if r.ttr_seconds and r.ttr_seconds > 0:
            ttr_values.append(r.ttr_seconds / 60.0)

    return {
        "total": len(records),
        "by_type": by_type,
        "avg_ttr_minutes": round(sum(ttr_values) / len(ttr_values), 1) if ttr_values else None,
        "records": [
            {
                "id": r.id,
                "lab_code": r.lab_code,
                "cluster": r.cluster,
                "failure_class": r.failure_class,
                "resolution_type": r.resolution_type,
                "resolved_by": r.resolved_by,
                "resolution_action": r.resolution_action,
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "ttr_minutes": round(r.ttr_seconds / 60.0, 1) if r.ttr_seconds else None,
            }
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Summit Report
# ---------------------------------------------------------------------------

@router.get("/dashboard/summit-report")
def dashboard_summit_report():
    """Summit week retrospective — mined from backup + live Babylon data."""
    import json as _json
    receipts = Path(__file__).parent.parent.parent.parent / "receipts"
    report_file = receipts / "summit-report.json"
    subjects_file = receipts / "summit-subjects.json"
    reclamation_file = receipts / "summit-reclamation.json"

    report = {}
    if report_file.exists():
        report = _json.loads(report_file.read_text())

    subjects = {}
    if subjects_file.exists():
        subjects = _json.loads(subjects_file.read_text())

    reclamation = {}
    if reclamation_file.exists():
        reclamation = _json.loads(reclamation_file.read_text())

    if not report:
        babylon = _load_latest_babylon()
        db_report = None
        try:
            from db.database import get_db as _gdb
            _db = next(_gdb())
            db_report = repository.get_latest_scan_snapshot(_db, "summit_report")
            _db.close()
        except Exception:
            pass
        if db_report:
            report = db_report

    labagator = {}
    try:
        from collectors.labagator import collect_labagator
        labagator_url = "http://labagator-backend.labagator-prod.svc:8080/api/v1"
        labagator = collect_labagator.summarize_labs(labagator_url, event_id=1)
    except Exception:
        pass

    has_data = bool(
        report.get("evaluations", {}).get("total")
        or report.get("aap", {}).get("total_jobs")
    )

    return {
        "report": report,
        "live_subjects": subjects,
        "reclamation": reclamation,
        "labagator": labagator,
        "has_data": has_data,
    }


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

@router.get("/dashboard/trends")
def dashboard_trends(
    hours: int = 24,
    bucket_minutes: int = 60,
    db: Session = Depends(get_db),
):
    """Time-bucketed evaluation and cluster health trends."""
    from db.models import EvaluationRecord

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    evals = (
        db.query(EvaluationRecord)
        .filter(
            EvaluationRecord.evaluated_at >= cutoff,
        )
        .order_by(EvaluationRecord.evaluated_at)
        .all()
    )

    buckets: Dict[str, Dict] = {}
    for ev in evals:
        ts = ev.evaluated_at
        if ts is None:
            continue
        bucket_key = ts.replace(
            minute=(ts.minute // bucket_minutes) * bucket_minutes,
            second=0, microsecond=0,
        ).isoformat()
        if bucket_key not in buckets:
            buckets[bucket_key] = {"pass": 0, "fail": 0, "warn": 0}
        b = buckets[bucket_key]
        if ev.outcome == "pass":
            b["pass"] += 1
        elif ev.outcome == "fail":
            b["fail"] += 1
        elif ev.outcome == "warn":
            b["warn"] += 1

    evaluation_trend = []
    for ts_key in sorted(buckets):
        b = buckets[ts_key]
        total = b["pass"] + b["fail"] + b["warn"]
        evaluation_trend.append({
            "timestamp": ts_key,
            "pass": b["pass"],
            "fail": b["fail"],
            "warn": b["warn"],
            "health_rate": round((b["pass"] + b["warn"]) / max(total, 1) * 100, 1),
        })

    scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
    cluster_health_trend = []
    for scan_file in sorted(scan_dir.glob("scan-*.json")):
        try:
            fname = scan_file.stem
            file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            if file_ts < cutoff:
                continue
            with open(scan_file) as f:
                scans = json.load(f)
            for s in scans:
                cluster_health_trend.append({
                    "timestamp": file_ts.isoformat(),
                    "cluster": s.get("cluster", ""),
                    "health_rate": s.get("health_rate", 0),
                    "avg_cpu_pct": s.get("avg_cpu_pct", 0),
                })
        except (ValueError, json.JSONDecodeError):
            continue

    failure_buckets: Dict[str, Dict[str, int]] = {}
    for ev in evals:
        if ev.outcome != "fail" or not ev.failure_class:
            continue
        ts = ev.evaluated_at
        if ts is None:
            continue
        bucket_key = ts.replace(
            minute=(ts.minute // bucket_minutes) * bucket_minutes,
            second=0, microsecond=0,
        ).isoformat()
        if bucket_key not in failure_buckets:
            failure_buckets[bucket_key] = {}
        fb = failure_buckets[bucket_key]
        fb[ev.failure_class] = fb.get(ev.failure_class, 0) + 1

    failure_trend = []
    for ts_key in sorted(failure_buckets):
        for fc, count in failure_buckets[ts_key].items():
            failure_trend.append({
                "timestamp": ts_key,
                "failure_class": fc,
                "count": count,
            })

    return {
        "evaluation_trend": evaluation_trend,
        "cluster_health_trend": cluster_health_trend,
        "failure_trend": failure_trend,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@router.get("/dashboard/nodes/{cluster}")
def dashboard_nodes(cluster: str):
    """Node-level metrics for a cluster from latest scan data."""
    scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
    scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)
    if not scan_files:
        raise HTTPException(404, "No scan data available")

    with open(scan_files[0]) as f:
        scans = json.load(f)

    cluster_scan = None
    for s in scans:
        if s.get("cluster") == cluster:
            cluster_scan = s
            break
    if not cluster_scan:
        raise HTTPException(404, f"No scan data for cluster {cluster}")

    return {
        "cluster": cluster,
        "timestamp": cluster_scan.get("timestamp"),
        "nodes": cluster_scan.get("nodes", 0),
        "compute_nodes": cluster_scan.get("compute_nodes", 0),
        "avg_cpu_pct": cluster_scan.get("avg_cpu_pct", 0),
        "hot_nodes": cluster_scan.get("hot_nodes", 0),
        "total_vms": cluster_scan.get("total_vms", 0),
        "vms_per_node": cluster_scan.get("vms_per_node", 0),
        "sandbox_active": cluster_scan.get("sandbox_active", 0),
        "sandbox_failing": cluster_scan.get("sandbox_failing", 0),
        "sandbox_crashloop": cluster_scan.get("sandbox_crashloop", 0),
        "ocp4_cluster_labs": cluster_scan.get("ocp4_cluster_labs", 0),
        "health_rate": cluster_scan.get("health_rate", 0),
        "dns_warnings": cluster_scan.get("dns_warnings", 0),
        "status": cluster_scan.get("status", "unknown"),
        "issues": cluster_scan.get("issues", []),
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@router.get("/dashboard/pipeline")
def dashboard_pipeline(
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Per-stage pass/fail/warn aggregation across the rubric pipeline."""
    if not lab_code and not cluster_name:
        from db.models import MVPipelineStage
        mv_rows = db.query(MVPipelineStage).all()
        mv_by_stage = {r.stage_id: r for r in mv_rows}
        stages = []
        for i, stage_id in enumerate(PIPELINE_STAGES):
            r = mv_by_stage.get(stage_id)
            if r:
                stages.append({
                    "stage_id": stage_id, "order": i,
                    "pass": r.pass_count, "fail": r.fail_count, "warn": r.warn_count,
                    "total": r.total, "health_rate": r.health_rate,
                })
            else:
                stages.append({
                    "stage_id": stage_id, "order": i,
                    "pass": 0, "fail": 0, "warn": 0, "total": 0, "health_rate": None,
                })
        return {"stages": stages, "lab_code": None, "cluster_name": None}

    from db.models import EvaluationRecord
    query = db.query(EvaluationRecord)
    if lab_code:
        query = query.filter(EvaluationRecord.lab_code == lab_code)
    if cluster_name:
        query = query.filter(EvaluationRecord.cluster_name == cluster_name)
    evals = query.limit(10000).all()

    stage_counts: Dict[str, Dict] = {}
    for ev in evals:
        sid = ev.stage_id
        if sid not in stage_counts:
            stage_counts[sid] = {"pass": 0, "fail": 0, "warn": 0}
        sc = stage_counts[sid]
        if ev.outcome == "pass":
            sc["pass"] += 1
        elif ev.outcome == "fail":
            sc["fail"] += 1
        elif ev.outcome == "warn":
            sc["warn"] += 1

    stages = []
    for i, stage_id in enumerate(PIPELINE_STAGES):
        sc = stage_counts.get(stage_id, {"pass": 0, "fail": 0, "warn": 0})
        total = sc["pass"] + sc["fail"] + sc["warn"]
        stages.append({
            "stage_id": stage_id,
            "order": i,
            "pass": sc["pass"],
            "fail": sc["fail"],
            "warn": sc["warn"],
            "total": total,
            "health_rate": round((sc["pass"] + sc["warn"]) / max(total, 1) * 100, 1) if total > 0 else None,
        })

    return {
        "stages": stages,
        "lab_code": lab_code,
        "cluster_name": cluster_name,
    }


@router.get("/dashboard/pipeline/{stage_id}")
def dashboard_pipeline_stage(stage_id: str, db: Session = Depends(get_db)):
    """Detailed data for a single pipeline stage."""
    from db.models import EvaluationRecord

    evals = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.stage_id == stage_id)
        .order_by(EvaluationRecord.id.desc())
        .limit(200)
        .all()
    )

    total = len(evals)
    passed = sum(1 for e in evals if e.outcome == "pass")
    warned = sum(1 for e in evals if e.outcome == "warn")
    failed = sum(1 for e in evals if e.outcome == "fail")

    failure_classes: Dict[str, int] = {}
    clusters_affected: Dict[str, int] = {}
    recent: List[Dict] = []

    for e in evals:
        if e.outcome == "fail":
            fc = e.failure_class or "unclassified"
            failure_classes[fc] = failure_classes.get(fc, 0) + 1
        if e.cluster_name:
            clusters_affected[e.cluster_name] = clusters_affected.get(e.cluster_name, 0) + 1
        if len(recent) < 20:
            recent.append({
                "run_id": e.run_id,
                "outcome": e.outcome,
                "failure_class": e.failure_class,
                "message": e.message,
                "cluster_name": e.cluster_name,
                "lab_code": e.lab_code,
                "evaluated_at": e.evaluated_at.isoformat() if e.evaluated_at else None,
            })

    return {
        "stage_id": stage_id,
        "total": total,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "health_rate": round((passed + warned) / max(total, 1) * 100, 1),
        "failure_classes": dict(sorted(failure_classes.items(), key=lambda x: -x[1])),
        "clusters_affected": dict(sorted(clusters_affected.items(), key=lambda x: -x[1])),
        "recent_evaluations": recent,
    }


# ---------------------------------------------------------------------------
# Nodes & Pods
# ---------------------------------------------------------------------------

@router.get("/dashboard/nodes-pods")
def dashboard_nodes_pods(db: Session = Depends(get_db)):
    """Node and pod summary across all clusters."""
    scan_data = _load_latest_scan()
    if not scan_data:
        return {"clusters": [], "totals": {}}

    all_cluster_evals = repository.get_all_cluster_summaries(db)

    clusters = []
    total_nodes = 0
    total_compute = 0
    total_vms = 0
    total_sandboxes = 0
    total_failing = 0
    total_crashloops = 0

    for s in scan_data:
        r = _scan_to_worker_format(s)
        n = r["nodes"]
        p = r["pods"]

        nodes_count = n["total_nodes"]
        compute = n["compute_nodes"]
        vms = p["total_vms"]
        active = p["sandbox_active"]
        failing = p["sandbox_failing"]
        crashloops = p["crashloops"]
        ocp4_labs = p["ocp4_labs"]

        total_nodes += nodes_count
        total_compute += compute
        total_vms += vms
        total_sandboxes += active
        total_failing += failing
        total_crashloops += crashloops

        cluster_name = r["cluster"]
        cluster_evals = all_cluster_evals.get(cluster_name, {})

        ns_by_type: Dict[str, int] = {}
        for ns in r["all_sandbox_namespaces"]:
            if "ocp4-cluster" in ns:
                ns_by_type["ocp4-cluster"] = ns_by_type.get("ocp4-cluster", 0) + 1
            elif "zt-rhelbu" in ns:
                ns_by_type["zt-rhel"] = ns_by_type.get("zt-rhel", 0) + 1
            elif "zt-ansiblebu" in ns:
                ns_by_type["zt-ansible"] = ns_by_type.get("zt-ansible", 0) + 1
            elif "zt-hpbu" in ns:
                ns_by_type["zt-hp"] = ns_by_type.get("zt-hp", 0) + 1
            else:
                ns_by_type["other"] = ns_by_type.get("other", 0) + 1

        clusters.append({
            "cluster": cluster_name,
            "status": n["status"],
            "nodes": nodes_count,
            "compute_nodes": compute,
            "avg_cpu": n["avg_cpu"],
            "hot_nodes": n["hot_nodes"],
            "total_vms": vms,
            "vms_per_node": round(vms / max(compute, 1), 1) if compute else 0,
            "sandbox_active": active,
            "sandbox_failing": failing,
            "crashloops": crashloops,
            "ocp4_labs": ocp4_labs,
            "new_failures": len(p["new_failures"]),
            "recovered": len(p["recovered"]),
            "recent_failures": p["new_failures"][:5],
            "sandbox_by_type": ns_by_type,
            "evaluations": {
                "total": cluster_evals.get("total_evaluations", 0),
                "passed": cluster_evals.get("passed", 0),
                "failed": cluster_evals.get("failed", 0),
                "health_rate": cluster_evals.get("health_rate", 0),
                "labs_seen": cluster_evals.get("labs_seen", 0),
                "labs_failing": cluster_evals.get("labs_failing", 0),
                "top_failures": dict(sorted(
                    cluster_evals.get("failure_classes", {}).items(),
                    key=lambda x: -x[1]
                )[:5]),
            },
        })

    return {
        "clusters": sorted(clusters, key=lambda c: c["cluster"]),
        "totals": {
            "nodes": total_nodes,
            "compute_nodes": total_compute,
            "total_vms": total_vms,
            "sandboxes": total_sandboxes,
            "failing": total_failing,
            "crashloops": total_crashloops,
        },
    }
