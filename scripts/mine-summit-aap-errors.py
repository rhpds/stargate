#!/usr/bin/env python3
"""Mine detailed AAP job data from event0 for summit week.

Extracts lab codes, job types (provision/destroy), durations, and playbook
info from the AAP API job list. The list endpoint doesn't return tracebacks
so we analyze available fields (name, playbook, elapsed, extra_vars).

Usage: python3 scripts/mine-summit-aap-errors.py
"""

import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


def get_aap_creds():
    """Get AAP credentials from OCP secret."""
    try:
        password = base64.b64decode(subprocess.run(
            ["oc", "get", "secret", "event0-monitor-basic-auth", "-n", "aap",
             "-o", "jsonpath={.data.password}"],
            capture_output=True, text=True, timeout=15
        ).stdout.strip()).decode()
        user = base64.b64decode(subprocess.run(
            ["oc", "get", "secret", "event0-monitor-basic-auth", "-n", "aap",
             "-o", "jsonpath={.data.user}"],
            capture_output=True, text=True, timeout=15
        ).stdout.strip()).decode()
        return user, password
    except Exception as e:
        print(f"Failed to get AAP creds: {e}")
        return None, None


def fetch_aap(url, user, password):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    return json.loads(resp.read())


def extract_lab_code(job_name):
    if not job_name:
        return "unknown"
    parts = job_name.split(".")
    if len(parts) >= 2:
        slug = parts[1]
        lb_parts = slug.split("-")
        if lb_parts and lb_parts[0].startswith("lb"):
            return lb_parts[0].upper()
        return slug[:40]
    return job_name[:40]


def extract_job_type(job):
    playbook = job.get("playbook", "")
    name = job.get("name", "").lower()
    if "destroy" in playbook or "destroy" in name:
        return "destroy"
    if "provision" in playbook or "provision" in name or "deploy" in playbook:
        return "provision"
    return "other"


def extract_catalog_item(job_name):
    if not job_name:
        return "unknown"
    parts = job_name.split()
    if parts:
        ci_parts = parts[0].split(".")
        if len(ci_parts) >= 2:
            return ".".join(ci_parts[:2])
    return "unknown"


def main():
    user, password = get_aap_creds()
    if not user or not password:
        print("Cannot get AAP credentials. Make sure you're logged into the cluster.")
        return 1

    base_url = "https://event0.apps.ocpv-infra01.dal12.infra.demo.redhat.com"
    print(f"Mining AAP job details from {base_url}...")

    # Fetch failed jobs
    all_failed = []
    url = f"{base_url}/api/v2/jobs/?status=failed&finished__gt=2026-05-05T00:00:00&finished__lt=2026-05-09T00:00:00&page_size=200&order_by=-finished"
    orig_host = urlparse(base_url).hostname

    page = 0
    while url and len(all_failed) < 1000:
        page += 1
        print(f"  Fetching page {page}... ({len(all_failed)} so far)")
        data = fetch_aap(url, user, password)
        all_failed.extend(data.get("results", []))
        url = data.get("next")
        if url and not url.startswith("http"):
            url = f"{base_url}{url}"
        elif url and urlparse(url).hostname != orig_host:
            break

    total_available = data.get("count", len(all_failed))
    print(f"  Fetched {len(all_failed)} of {total_available} failed jobs")

    # Analyze
    by_lab = defaultdict(lambda: {"total": 0, "provision": 0, "destroy": 0, "other": 0, "avg_elapsed": 0, "catalog_items": set()})
    by_type = defaultdict(int)
    by_playbook = defaultdict(int)
    by_catalog = defaultdict(lambda: {"total": 0, "provision": 0, "destroy": 0, "other": 0})
    durations = []
    by_day = defaultdict(lambda: {"total": 0, "provision": 0, "destroy": 0, "other": 0})

    for job in all_failed:
        lab = extract_lab_code(job.get("name", ""))
        job_type = extract_job_type(job)
        catalog = extract_catalog_item(job.get("name", ""))
        elapsed = job.get("elapsed", 0)
        finished = job.get("finished", "")
        playbook = job.get("playbook", "unknown")

        by_lab[lab]["total"] += 1
        by_lab[lab][job_type] += 1
        by_lab[lab]["catalog_items"].add(catalog)
        if elapsed:
            durations.append(elapsed)

        by_type[job_type] += 1
        by_playbook[playbook] += 1

        by_catalog[catalog]["total"] += 1
        by_catalog[catalog][job_type] += 1

        if finished:
            day = finished[:10]
            by_day[day]["total"] += 1
            by_day[day][job_type] += 1

    # Build report
    top_failing_labs = {}
    for lab, stats in sorted(by_lab.items(), key=lambda x: -x[1]["total"])[:20]:
        top_failing_labs[lab] = {
            "failed": stats["total"],
            "provision_failures": stats["provision"],
            "destroy_failures": stats["destroy"],
            "catalog_items": sorted(stats["catalog_items"]),
        }

    top_catalogs = {}
    for cat, stats in sorted(by_catalog.items(), key=lambda x: -x[1]["total"])[:15]:
        top_catalogs[cat] = {
            "failed": stats["total"],
            "provision": stats["provision"],
            "destroy": stats["destroy"],
        }

    top_playbooks = dict(sorted(by_playbook.items(), key=lambda x: -x[1])[:10])

    report = {
        "controller": "event0",
        "total_failed_fetched": len(all_failed),
        "total_failed_available": total_available,
        "by_type": dict(by_type),
        "by_day": {k: dict(v) for k, v in sorted(by_day.items())},
        "top_failing_labs": top_failing_labs,
        "top_catalogs": top_catalogs,
        "top_playbooks": top_playbooks,
        "avg_duration_minutes": round(sum(durations) / max(len(durations), 1) / 60, 1),
        "max_duration_minutes": round(max(durations, default=0) / 60, 1),
    }

    output_path = Path(__file__).parent.parent / "receipts" / "summit-aap-errors.json"
    output_path.write_text(json.dumps(report, indent=2, default=list))
    print(f"\nSaved to {output_path}")

    print(f"\nJob type breakdown:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print(f"\nTop failing labs:")
    for lab, stats in list(top_failing_labs.items())[:10]:
        print(f"  {lab}: {stats['failed']} failed ({stats['provision_failures']} provision, {stats['destroy_failures']} destroy)")
    print(f"\nTop playbooks:")
    for pb, c in list(top_playbooks.items())[:5]:
        print(f"  {c:4d}  {pb}")
    print(f"\nDuration: avg {report['avg_duration_minutes']}min, max {report['max_duration_minutes']}min")

    # Merge into summit report
    summit_path = Path(__file__).parent.parent / "receipts" / "summit-report.json"
    if summit_path.exists():
        summit = json.loads(summit_path.read_text())
        if "aap" not in summit:
            # Re-add AAP section from the original mining
            aap_event0_path = Path(__file__).parent.parent / "receipts" / "summit-aap-event0.json"
            if aap_event0_path.exists():
                aap_event0 = json.loads(aap_event0_path.read_text())
                summit["aap"] = {
                    "event0": aap_event0,
                    "total_jobs": aap_event0.get("total_summit_jobs", 0),
                    "total_failed": aap_event0.get("total_failed", 0),
                    "overall_success_rate": aap_event0.get("overall_success_rate", 0),
                    "by_day": aap_event0.get("by_day", {}),
                }

        if "aap" in summit:
            summit["aap"]["top_failing_labs"] = top_failing_labs
            summit["aap"]["top_catalogs"] = top_catalogs
            summit["aap"]["top_playbooks"] = top_playbooks
            summit["aap"]["top_errors"] = top_playbooks
            summit["aap"]["failure_breakdown"] = {
                "by_type": dict(by_type),
                "avg_duration_minutes": report["avg_duration_minutes"],
                "max_duration_minutes": report["max_duration_minutes"],
            }

        if "data_coverage" in summit:
            summit["data_coverage"]["aap_jobs"] = {
                "controllers": ["event0"],
                "days": ["2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"],
                "total_jobs": summit.get("aap", {}).get("total_jobs", 22638),
                "failed_analyzed": len(all_failed),
                "note": f"Full job history from event0 (dal12). {len(all_failed)} of {total_available} failed jobs analyzed. Event1 (wdc07) on infra02 not queried.",
            }

        summit_path.write_text(json.dumps(summit, indent=2, default=list))
        print(f"\nUpdated {summit_path}")


if __name__ == "__main__":
    sys.exit(main() or 0)
