#!/usr/bin/env python3
"""Load summit week data from backup into StarGate DB as a summit report.

Extracts May 5-8 2026 data from the pg_dump backup, analyzes it, and
stores a structured summit report in the scan_snapshots table.

Usage: python3 scripts/load-summit-data.py
"""

import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKUP_FILE = Path(__file__).parent.parent / "backups" / "stargate-20260511-125245.sql.gz"
SUMMIT_START = "2026-05-05"
SUMMIT_END = "2026-05-09"  # exclusive


def parse_backup():
    """Parse the pg_dump backup and extract summit-period rows."""
    tables = {}
    current_table = None
    current_cols = None

    with gzip.open(BACKUP_FILE, "rt") as f:
        for line in f:
            if line.startswith("COPY public."):
                parts = line.split("(", 1)
                current_table = parts[0].replace("COPY public.", "").strip()
                col_str = parts[1].rstrip().rstrip(";").rstrip(")").strip()
                current_cols = [c.strip().strip('"') for c in col_str.split(",")]
                tables[current_table] = {"cols": current_cols, "rows": []}
            elif line.startswith("\\."):
                current_table = None
                current_cols = None
            elif current_table and current_cols and line.strip():
                fields = line.rstrip("\n").split("\t")
                if len(fields) == len(current_cols):
                    row = dict(zip(current_cols, fields))
                    tables[current_table]["rows"].append(row)

    return tables


def is_summit_period(date_str):
    """Check if a date string falls in summit week."""
    if not date_str or date_str == "\\N":
        return False
    return SUMMIT_START <= date_str[:10] < SUMMIT_END


def analyze_summit(tables):
    """Build summit analytics from extracted data."""
    report = {
        "event_name": "Red Hat Summit 2026",
        "dates": {"start": "2026-05-05", "end": "2026-05-08"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # --- Evaluations ---
    evals = tables.get("evaluations", {}).get("rows", [])
    summit_evals = [e for e in evals if is_summit_period(e.get("evaluated_at", ""))]

    outcomes = defaultdict(int)
    failure_classes = defaultdict(int)
    by_lab = defaultdict(lambda: {"pass": 0, "fail": 0, "warn": 0, "total": 0})
    by_cluster = defaultdict(lambda: {"pass": 0, "fail": 0, "warn": 0, "total": 0})
    by_stage = defaultdict(lambda: {"pass": 0, "fail": 0, "warn": 0, "total": 0})
    by_day = defaultdict(lambda: {"pass": 0, "fail": 0, "warn": 0, "total": 0})
    hourly_timeline = defaultdict(lambda: {"pass": 0, "fail": 0, "total": 0})

    for e in summit_evals:
        outcome = e.get("outcome", "unknown")
        outcomes[outcome] += 1

        fc = e.get("failure_class", "")
        if fc and fc != "\\N":
            failure_classes[fc] += 1

        lab = e.get("lab_code", "unknown")
        by_lab[lab][outcome] = by_lab[lab].get(outcome, 0) + 1
        by_lab[lab]["total"] += 1

        cluster = e.get("cluster_name", "unknown")
        by_cluster[cluster][outcome] = by_cluster[cluster].get(outcome, 0) + 1
        by_cluster[cluster]["total"] += 1

        stage = e.get("stage_id", "unknown")
        by_stage[stage][outcome] = by_stage[stage].get(outcome, 0) + 1
        by_stage[stage]["total"] += 1

        ts = e.get("evaluated_at", "")
        if ts and ts != "\\N":
            day = ts[:10]
            by_day[day][outcome] = by_day[day].get(outcome, 0) + 1
            by_day[day]["total"] += 1

            hour_key = ts[:13]
            hourly_timeline[hour_key][outcome] = hourly_timeline[hour_key].get(outcome, 0) + 1
            hourly_timeline[hour_key]["total"] += 1

    report["evaluations"] = {
        "total": len(summit_evals),
        "outcomes": dict(outcomes),
        "pass_rate": round(outcomes.get("pass", 0) / max(len(summit_evals), 1) * 100, 1),
        "failure_classes": dict(sorted(failure_classes.items(), key=lambda x: -x[1])[:30]),
        "total_failure_classes": len(failure_classes),
    }

    # --- Runs ---
    runs = tables.get("runs", {}).get("rows", [])
    summit_runs = [r for r in runs if is_summit_period(r.get("started_at", ""))]
    run_statuses = defaultdict(int)
    for r in summit_runs:
        run_statuses[r.get("status", "unknown")] += 1

    report["runs"] = {
        "total": len(summit_runs),
        "statuses": dict(run_statuses),
    }

    # --- Evidence ---
    evidence = tables.get("evidence", {}).get("rows", [])
    summit_evidence = [ev for ev in evidence if is_summit_period(ev.get("timestamp", ""))]
    evidence_types = defaultdict(int)
    for ev in summit_evidence:
        evidence_types[ev.get("type", "unknown")] += 1

    report["evidence"] = {
        "total": len(summit_evidence),
        "by_type": dict(evidence_types),
    }

    # --- Events ---
    events = tables.get("event_log", {}).get("rows", [])
    summit_events = [ev for ev in events if is_summit_period(ev.get("timestamp", ""))]
    event_types = defaultdict(int)
    systemic_count = 0
    for ev in summit_events:
        event_types[ev.get("event_type", "unknown")] += 1
        if ev.get("systemic") == "t":
            systemic_count += 1

    report["events"] = {
        "total": len(summit_events),
        "by_type": dict(event_types),
        "systemic": systemic_count,
    }

    # --- Labs ---
    lab_list = []
    for lab, stats in sorted(by_lab.items(), key=lambda x: -x[1]["total"]):
        total = stats["total"]
        passed = stats.get("pass", 0)
        failed = stats.get("fail", 0)
        lab_list.append({
            "lab_code": lab,
            "total_evals": total,
            "passed": passed,
            "failed": failed,
            "warned": stats.get("warn", 0),
            "pass_rate": round(passed / max(total, 1) * 100, 1),
        })
    report["labs"] = {
        "total": len(lab_list),
        "labs": lab_list[:50],
        "top_failing": [l for l in lab_list if l["failed"] > 0][:20],
    }

    # --- Clusters ---
    cluster_list = []
    for cluster, stats in sorted(by_cluster.items(), key=lambda x: -x[1]["total"]):
        total = stats["total"]
        passed = stats.get("pass", 0)
        cluster_list.append({
            "cluster": cluster,
            "total_evals": total,
            "passed": passed,
            "failed": stats.get("fail", 0),
            "pass_rate": round(passed / max(total, 1) * 100, 1),
        })
    report["clusters"] = cluster_list

    # --- Stages ---
    stage_list = []
    for stage, stats in sorted(by_stage.items(), key=lambda x: -x[1].get("fail", 0), reverse=True):
        total = stats["total"]
        passed = stats.get("pass", 0)
        stage_list.append({
            "stage_id": stage,
            "total": total,
            "passed": passed,
            "failed": stats.get("fail", 0),
            "pass_rate": round(passed / max(total, 1) * 100, 1),
        })
    report["stages"] = stage_list

    # --- Daily breakdown ---
    day_list = []
    for day in sorted(by_day.keys()):
        stats = by_day[day]
        total = stats["total"]
        passed = stats.get("pass", 0)
        day_list.append({
            "date": day,
            "total": total,
            "passed": passed,
            "failed": stats.get("fail", 0),
            "pass_rate": round(passed / max(total, 1) * 100, 1),
        })
    report["daily"] = day_list

    # --- Hourly timeline ---
    timeline = []
    for hour in sorted(hourly_timeline.keys()):
        stats = hourly_timeline[hour]
        timeline.append({
            "hour": hour,
            "total": stats["total"],
            "passed": stats.get("pass", 0),
            "failed": stats.get("fail", 0),
        })
    report["hourly_timeline"] = timeline

    # --- LLM Metrics ---
    llm = tables.get("llm_metrics", {}).get("rows", [])
    summit_llm = [m for m in llm if is_summit_period(m.get("called_at", ""))]
    report["llm"] = {
        "total_calls": len(summit_llm),
    }

    # --- Proposed Classifications ---
    proposals = tables.get("proposed_classifications", {}).get("rows", [])
    summit_proposals = [p for p in proposals if is_summit_period(p.get("proposed_at", ""))]
    report["classifications"] = {
        "total_proposed": len(summit_proposals),
        "reviewed": sum(1 for p in summit_proposals if p.get("reviewed") == "t"),
        "approved": sum(1 for p in summit_proposals if p.get("approved") == "t"),
    }

    return report


def persist_report(report):
    """Save the summit report to the database."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    if "STARGATE_DATABASE_URL" not in os.environ:
        raise RuntimeError("STARGATE_DATABASE_URL environment variable is required")

    from db.database import get_db
    from db import repository

    db = next(get_db())
    repository.save_scan_snapshot(db, "summit_report", report)
    db.close()
    print(f"Summit report saved to database (scan_type=summit_report)")


def main():
    if not BACKUP_FILE.exists():
        print(f"Backup file not found: {BACKUP_FILE}", file=sys.stderr)
        return 1

    print(f"Parsing backup: {BACKUP_FILE}")
    tables = parse_backup()

    for name, data in tables.items():
        print(f"  {name}: {len(data['rows'])} rows")

    print("\nAnalyzing summit week (May 5-8)...")
    report = analyze_summit(tables)

    print(f"\n=== Summit Report ===")
    print(f"Evaluations: {report['evaluations']['total']} ({report['evaluations']['pass_rate']}% pass rate)")
    print(f"Runs: {report['runs']['total']}")
    print(f"Evidence records: {report['evidence']['total']}")
    print(f"Events: {report['events']['total']} ({report['events']['systemic']} systemic)")
    print(f"Labs evaluated: {report['labs']['total']}")
    print(f"Clusters: {len(report['clusters'])}")
    print(f"Failure classes: {report['evaluations']['total_failure_classes']}")
    print(f"Daily breakdown:")
    for d in report["daily"]:
        print(f"  {d['date']}: {d['total']} evals, {d['pass_rate']}% pass, {d['failed']} failures")

    # Save to file
    output = Path(__file__).parent.parent / "receipts" / "summit-report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(f"\nSaved to {output}")

    # Save to DB
    try:
        persist_report(report)
    except Exception as e:
        print(f"DB persist failed (will use file): {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
