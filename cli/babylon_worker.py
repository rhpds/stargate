"""Babylon control plane worker — collects Poolboy, Anarchy, and CatalogItem data.

Runs against ocp-us-east-1 where the Babylon control plane lives.
Separate from the per-cluster lab workers — this collects provisioning
and pool state, not namespace-level evidence.

Usage:
  python3 -m cli.babylon_worker --once
  python3 -m cli.babylon_worker --interval 300
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

SECRETS_DIR = Path(__file__).parent.parent / "secrets"
KUBECONFIG = str(SECRETS_DIR / "kubeconfig")  # ocp-us-east-1


def _oc(args: List[str], timeout: int = 30) -> Optional[str]:
    env = {**os.environ, "KUBECONFIG": KUBECONFIG}
    try:
        r = subprocess.run(["oc"] + args, capture_output=True, text=True, timeout=timeout, env=env)
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return None


def collect_pool_summary() -> Dict:
    """Collect ResourcePool capacity summary."""
    from collectors.poolboy.collect_poolboy import collect_resource_pool

    raw = _oc(["get", "resourcepools", "-n", "poolboy", "-o", "json"])
    if not raw:
        return {"error": "failed to get resourcepools"}

    data = json.loads(raw)
    pools = data.get("items", [])

    total = len(pools)
    exhausted = []
    low = []
    all_pools = []

    for p in pools:
        name = p.get("metadata", {}).get("name", "")
        ev = collect_resource_pool(p)
        obs = ev.observed

        pool_entry = {
            "name": name,
            "available": obs.get("total_handles", 0),
            "ready": obs.get("ready_handles", 0),
            "min": obs.get("min_available", 0),
            "is_summit": "summit-2026" in name,
        }
        all_pools.append(pool_entry)

        if obs.get("pool_exhausted"):
            exhausted.append({"name": name, "min": obs["min_available"]})
        elif obs.get("pool_low"):
            low.append({"name": name, "available": obs["total_handles"], "min": obs["min_available"]})

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_pools": total,
        "exhausted": exhausted,
        "low": low,
        "all_pools": all_pools,
        "summit_pools": [p for p in all_pools if p["is_summit"]],
        "status": "critical" if exhausted else "warning" if len(low) > 10 else "healthy",
    }


def collect_provision_summary() -> Dict:
    """Collect AnarchySubject provisioning summary."""
    from collectors.babylon.collect_anarchy_state import collect_anarchysubject

    raw = _oc(["get", "anarchysubjects", "-A", "--no-headers"])
    if not raw:
        return {"error": "failed to get anarchysubjects"}

    by_state: Dict[str, int] = {}
    total = 0
    failed = 0
    started = 0
    summit = {"total": 0, "started": 0, "failed": 0}

    for line in raw.strip().split("\n"):
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue

        ns, name, governor, state = parts[0], parts[1], parts[2], parts[3]
        total += 1
        by_state[state] = by_state.get(state, 0) + 1

        if "failed" in state:
            failed += 1
        if state == "started":
            started += 1

        if "summit-2026" in name or "summit-2026" in governor:
            summit["total"] += 1
            if state == "started":
                summit["started"] += 1
            if "failed" in state:
                summit["failed"] += 1

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "started": started,
        "failed": failed,
        "by_state": by_state,
        "failure_rate": round(failed / max(total, 1) * 100, 1),
        "summit_2026": summit,
    }


def collect_catalog_summary() -> Dict:
    """Collect CatalogItem counts and names per namespace."""
    result = {}
    for ns in ["babylon-catalog-event", "babylon-catalog-prod", "babylon-catalog-dev"]:
        raw = _oc(["get", "catalogitems", "-n", ns, "--no-headers"])
        if raw:
            lines = [l for l in raw.strip().split("\n") if l]
            result[ns] = len(lines)
        else:
            result[ns] = 0
    return result


def collect_catalog_items() -> List[Dict]:
    """Collect CatalogItem details from all catalog namespaces."""
    items = []
    for ns in ["babylon-catalog-event", "babylon-catalog-prod", "babylon-catalog-dev"]:
        raw = _oc(["get", "catalogitems", "-n", ns, "-o", "json"])
        if not raw:
            continue
        try:
            data = json.loads(raw)
            for item in data.get("items", []):
                meta = item.get("metadata", {})
                spec = item.get("spec", {})
                items.append({
                    "name": meta.get("name", ""),
                    "namespace": ns,
                    "category": ns.replace("babylon-catalog-", ""),
                    "display_name": spec.get("displayName", meta.get("name", "")),
                    "description": str(spec.get("description", "") or "")[:200],
                    "disabled": spec.get("disabled", False),
                    "provider": spec.get("provider", ""),
                    "labels": meta.get("labels", {}),
                    "created": meta.get("creationTimestamp", ""),
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return items


def collect_workshop_summary() -> Dict:
    """Collect Workshop/MultiWorkshop status."""
    raw = _oc(["get", "workshops", "-A", "--no-headers"])
    workshops = 0
    if raw:
        workshops = len([l for l in raw.strip().split("\n") if l])

    raw_mw = _oc(["get", "multiworkshops", "-A", "--no-headers"])
    multiworkshops = 0
    if raw_mw:
        multiworkshops = len([l for l in raw_mw.strip().split("\n") if l])

    return {"workshops": workshops, "multiworkshops": multiworkshops}


_SUBJECT_COLUMNS = (
    "NAME:.metadata.name,"
    "NS:.metadata.namespace,"
    "STATE:.spec.vars.current_state,"
    "CONSOLE:.spec.vars.provision_data.openshift_cluster_console_url,"
    "API:.spec.vars.provision_data.openshift_api_server_url"
)


def _parse_subject_line(line: str) -> Optional[Dict]:
    """Parse a custom-columns line into a subject dict."""
    parts = line.split(None, 4)
    if len(parts) < 3:
        return None
    name = parts[0]
    ns = parts[1] if len(parts) > 1 else ""
    state = parts[2] if len(parts) > 2 else "unknown"
    console = parts[3] if len(parts) > 3 and parts[3] != "<none>" else ""
    api_url = parts[4] if len(parts) > 4 and parts[4] != "<none>" else ""
    if state == "<none>":
        state = "unknown"
    return {"name": name, "namespace": ns, "state": state, "console_url": console, "api_url": api_url}


def collect_summit_namespace_mapping() -> Dict[str, List[Dict]]:
    """Map summit labs to their provisioned instances via AnarchySubjects."""
    raw = _oc([
        "get", "anarchysubjects", "-n", "babylon-anarchy-events",
        "--no-headers", "-o", f"custom-columns={_SUBJECT_COLUMNS}",
    ], timeout=60)
    if not raw:
        return {}

    by_lab: Dict[str, List[Dict]] = {}
    for line in raw.strip().split("\n"):
        subj = _parse_subject_line(line)
        if not subj or "summit-2026" not in subj["name"]:
            continue

        name_parts = subj["name"].split(".")
        if len(name_parts) < 2:
            continue
        slug = name_parts[1]
        lb_parts = slug.split("-")
        if lb_parts and lb_parts[0].startswith("lb"):
            lb_code = lb_parts[0].upper()
        elif slug.startswith("ai-"):
            lb_code = slug
        else:
            continue

        if lb_code not in by_lab:
            by_lab[lb_code] = []
        by_lab[lb_code].append({
            "anarchy_name": subj["name"],
            "state": subj["state"],
            "console_url": subj["console_url"],
            "api_url": subj["api_url"],
        })

    return by_lab


def collect_all_instance_mapping() -> Dict[str, List[Dict]]:
    """Map ALL labs to their provisioned instances via AnarchySubjects across all namespaces."""
    raw = _oc([
        "get", "anarchysubjects", "-A",
        "--no-headers", "-o", f"custom-columns={_SUBJECT_COLUMNS}",
    ], timeout=90)
    if not raw:
        return {}

    by_lab: Dict[str, List[Dict]] = {}
    for line in raw.strip().split("\n"):
        subj = _parse_subject_line(line)
        if not subj:
            continue

        name_parts = subj["name"].split(".")
        if len(name_parts) < 2:
            continue
        prefix = name_parts[0]
        slug = name_parts[1]

        lb_parts = slug.split("-")
        if lb_parts and lb_parts[0].startswith("lb"):
            lb_code = lb_parts[0].upper()
        elif slug.startswith("ai-") or slug.startswith("zt-"):
            lb_code = slug
        else:
            lb_code = slug

        if lb_code not in by_lab:
            by_lab[lb_code] = []
        by_lab[lb_code].append({
            "anarchy_name": subj["name"],
            "namespace": subj["namespace"],
            "state": subj["state"],
            "prefix": prefix,
            "console_url": subj["console_url"],
            "api_url": subj["api_url"],
        })

    return by_lab


def run_collection() -> Dict:
    """Run full Babylon control plane collection."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] Babylon control plane collection starting...")

    results = {}

    print("  Collecting pool capacity...")
    results["pools"] = collect_pool_summary()
    pools = results["pools"]
    print(f"    {pools.get('total_pools', 0)} pools, {len(pools.get('exhausted', []))} exhausted, {len(pools.get('low', []))} low")

    print("  Collecting provisioning state...")
    results["provisioning"] = collect_provision_summary()
    prov = results["provisioning"]
    print(f"    {prov.get('total', 0)} subjects, {prov.get('started', 0)} started, {prov.get('failed', 0)} failed ({prov.get('failure_rate', 0)}%)")
    summit = prov.get("summit_2026", {})
    if summit.get("total", 0) > 0:
        print(f"    Summit 2026: {summit['total']} total, {summit['started']} started, {summit['failed']} failed")

    print("  Collecting catalog summary...")
    results["catalog"] = collect_catalog_summary()
    print(f"    Event: {results['catalog'].get('babylon-catalog-event', 0)}, Prod: {results['catalog'].get('babylon-catalog-prod', 0)}")

    print("  Collecting catalog items...")
    results["catalog_items"] = collect_catalog_items()
    print(f"    {len(results['catalog_items'])} catalog items loaded")

    print("  Collecting workshop summary...")
    results["workshops"] = collect_workshop_summary()
    print(f"    Workshops: {results['workshops']['workshops']}, MultiWorkshops: {results['workshops']['multiworkshops']}")

    # Save core OCP data immediately so dashboard has provisioning info
    _save_results(results)

    # Instance mappings (slower — full subject list)
    print("  Collecting all lab-to-instance mapping...")
    results["instance_mapping"] = collect_all_instance_mapping()
    im = results["instance_mapping"]
    print(f"    {len(im)} labs mapped, {sum(len(v) for v in im.values())} total instances")

    print("  Collecting summit lab-to-namespace mapping...")
    results["summit_mapping"] = collect_summit_namespace_mapping()
    sm = results["summit_mapping"]
    print(f"    {len(sm)} summit labs, {sum(len(v) for v in sm.values())} summit instances")

    # Labagator (external HTTP — may be slow/unreachable)
    print("  Collecting Labagator data...")
    try:
        from collectors.labagator.collect_labagator import summarize_labs
        results["labagator"] = summarize_labs()
        lg = results["labagator"]
        print(f"    {lg.get('total_labs', 0)} labs, {lg.get('total_sessions', 0)} sessions")
    except Exception as e:
        results["labagator"] = {"error": str(e)}
        print(f"    Labagator error: {e}")

    # Demolition (external HTTP — may be slow/unreachable)
    print("  Collecting Demolition data...")
    try:
        from collectors.demolition.collect_demolition import summarize_sessions, find_tracked_sessions
        results["demolition"] = summarize_sessions()
        event_prefix = os.environ.get("STARGATE_EVENT_PREFIX", "")
        results["demolition_tracked"] = find_tracked_sessions(prefix=event_prefix)
        results["demolition_summit"] = results["demolition_tracked"]
        demo = results["demolition"]
        print(f"    {demo.get('total_sessions', 0)} sessions, {demo.get('overall_pass_rate', 0)}% pass rate")
    except Exception as e:
        results["demolition"] = {"error": str(e)}
        print(f"    Demolition error: {e}")

    # Save again with Labagator/Demolition data if they succeeded
    _save_results(results)
    return results


def _save_results(results: Dict):
    """Save collection results to scan-history files and database."""
    # Save to history
    history_dir = Path(__file__).parent.parent / "scan-history"
    history_dir.mkdir(exist_ok=True)
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (history_dir / f"babylon-{ts_file}.json").write_text(json.dumps(results, indent=2))

    # Persist to database
    try:
        from db.database import get_db
        from db import repository
        db = next(get_db())
        repository.save_scan_snapshot(db, "babylon_scan", results)
        db.close()
    except Exception:
        pass

    print(f"  Saved to scan-history/babylon-{ts_file}.json")


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="babylon-worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    if not os.path.exists(KUBECONFIG):
        print("No kubeconfig for ocp-us-east-1", file=sys.stderr)
        return 1

    if args.once:
        results = run_collection()
        print(json.dumps(results, indent=2))
        return 0

    print(f"Babylon worker running every {args.interval}s")
    while True:
        run_collection()
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)
