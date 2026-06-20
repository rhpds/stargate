"""AAP collector — fetches provisioning job data from Ansible Automation Platform controllers.

Queries event0 (dal12) and event1 (wdc07) for failed and successful jobs,
extracts lab codes, clusters, failing tasks, and error messages.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import ssl
import time


def _make_ssl_ctx():
    ctx = ssl.create_default_context()
    if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.aap")

AAP_CONTROLLERS = [
    {
        "name": "event0",
        "url": os.environ.get("STARGATE_AAP_EVENT0_URL", ""),
        "user": os.environ.get("STARGATE_AAP_EVENT0_USER", "monitor"),
        "password": os.environ.get("STARGATE_AAP_EVENT0_PASS", ""),
    },
    {
        "name": "event1",
        "url": os.environ.get("STARGATE_AAP_EVENT1_URL", ""),
        "user": os.environ.get("STARGATE_AAP_EVENT1_USER", "monitor"),
        "password": os.environ.get("STARGATE_AAP_EVENT1_PASS", ""),
    },
]

_cache: Dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 300

_EVENT_PREFIX = os.environ.get("STARGATE_EVENT_PREFIX", "")
_LAB_CODE_PATTERN = re.compile(
    rf'(?:{re.escape(_EVENT_PREFIX)}\.)?(lb\d{{4}}|zt-[a-z]+|launchpad-[a-z]+)',
    re.IGNORECASE,
) if _EVENT_PREFIX else re.compile(r'(?:\w+\.)(lb\d{4}|zt-[a-z-]+|launchpad-[a-z-]+)', re.IGNORECASE)


def extract_lab_code(job_name: str) -> Optional[str]:
    """Extract lab code from AAP job name."""
    m = _LAB_CODE_PATTERN.search(job_name)
    if m:
        return m.group(1).upper()
    return None


def group_failures(failures: List[Dict]) -> List[Dict]:
    """Group failures by failing task + error."""
    groups: Dict[str, Dict] = {}
    for f in failures:
        key = f.get("failing_task", "unknown")
        if key not in groups:
            groups[key] = {
                "failing_task": key,
                "error": f.get("error", ""),
                "type": f.get("type", ""),
                "count": 0,
                "clusters": set(),
                "labs": set(),
            }
        groups[key]["count"] += 1
        if f.get("cluster"):
            groups[key]["clusters"].add(f["cluster"])
        lab = f.get("lab_code")
        if lab:
            groups[key]["labs"].add(lab)

    result = []
    for g in sorted(groups.values(), key=lambda x: -x["count"]):
        g["clusters"] = sorted(g["clusters"])
        g["labs"] = sorted(g["labs"])
        result.append(g)
    return result


def collect_aap_jobs(hours: int = 24) -> Dict:
    """Fetch provisioning job data from AAP controllers. Cached 5 min."""
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    all_failures = []
    total_jobs = 0
    successful = 0
    failed = 0
    running = 0
    provision_total = 0
    provision_success = 0

    _event_cache: Dict[str, Dict] = {}

    for controller in AAP_CONTROLLERS:
        if not controller["url"] or not controller["password"]:
            continue
        try:
            failed_jobs = _fetch_jobs(controller, f"status=failed&finished__gt={cutoff}&page_size=200")
            for job in failed_jobs:
                name = job.get("name", "")
                lab_code = extract_lab_code(name)
                catalog_parts = name.split(".")
                catalog_item = ".".join(catalog_parts[:2]) if len(catalog_parts) >= 2 else name

                job_type = "provision" if "provision" in name else "destroy" if "destroy" in name else "other"

                failing_task = ""
                error_msg = ""
                result_traceback = job.get("result_traceback", "") or ""
                if result_traceback:
                    lines = result_traceback.strip().split("\n")
                    error_msg = lines[-1][:200] if lines else ""
                    for line in lines:
                        if "TASK [" in line:
                            failing_task = line.split("TASK [")[1].split("]")[0] if "TASK [" in line else ""

                if not failing_task:
                    failing_task = job.get("job_explanation", "")[:100] or ""
                if not error_msg:
                    error_msg = job.get("job_explanation", "")[:200] or ""

                if not failing_task or not error_msg:
                    catalog_key = catalog_item + ("_destroy" if "destroy" in name else "_prov")
                    if catalog_key in _event_cache:
                        cached = _event_cache[catalog_key]
                        if not failing_task:
                            failing_task = cached.get("task", "")
                        if not error_msg:
                            error_msg = cached.get("error", "")
                    elif len(_event_cache) < 50:
                        try:
                            job_id = job.get("id")
                            events = _fetch_job_events(controller, job_id)
                            if events:
                                ev = events[0]
                                task = ev.get("task", "") or ""
                                res = ev.get("event_data", {}).get("res", {})
                                msg = (res.get("msg", "") or "")[:200] or ""
                                _event_cache[catalog_key] = {"task": task, "error": msg}
                                if not failing_task:
                                    failing_task = task
                                if not error_msg:
                                    error_msg = msg
                        except Exception:
                            pass
                if not failing_task:
                    failing_task = "Unknown task"
                if not error_msg:
                    error_msg = "Unknown error"

                cluster = ""
                extra_vars = job.get("extra_vars", "")
                if isinstance(extra_vars, str) and extra_vars != "{}":
                    try:
                        ev = json.loads(extra_vars)
                        host = ev.get("bastion_ansible_host", "") or ev.get("target_host", "")
                        if host:
                            # "ssh.<cluster>.<domain>" → "<cluster>"
                            parts = host.replace("ssh.", "").split(".")
                            cluster = parts[0] if parts else host
                        if not cluster:
                            for k, v in ev.items():
                                if isinstance(v, str) and re.search(r'ocpv\d+|ocp-', v):
                                    m = re.search(r'(ocpv\d+|ocp-[\w-]+)', v)
                                    if m:
                                        cluster = m.group(1)
                                        break
                    except Exception:
                        pass

                all_failures.append({
                    "job_id": job.get("id"),
                    "controller": controller["name"],
                    "type": job_type,
                    "name": name,
                    "lab_code": lab_code,
                    "catalog_item": catalog_item,
                    "cluster": cluster,
                    "failing_task": failing_task,
                    "error": error_msg,
                    "finished": job.get("finished"),
                    "duration_minutes": round((job.get("elapsed", 0) or 0) / 60, 1),
                    "job_url": f"{controller['url']}/#/jobs/{job.get('id')}/output",
                })

            counts = _fetch_job_counts(controller, cutoff)
            total_jobs += counts.get("total", 0)
            successful += counts.get("successful", 0)
            failed += counts.get("failed", 0)
            running += counts.get("running", 0)
            provision_total += counts.get("provision_total", 0)
            provision_success += counts.get("provision_success", 0)

        except Exception as e:
            logger.warning(f"AAP collection failed for {controller['name']}: {e}")

    by_error = group_failures(all_failures)

    by_cluster: Dict[str, Dict] = {}
    for f in all_failures:
        c = f.get("cluster") or "unknown"
        if c not in by_cluster:
            by_cluster[c] = {"total": 0, "provision": 0, "destroy": 0}
        by_cluster[c]["total"] += 1
        if f["type"] == "provision":
            by_cluster[c]["provision"] += 1
        elif f["type"] == "destroy":
            by_cluster[c]["destroy"] += 1

    by_lab: Dict[str, Dict] = {}
    for f in all_failures:
        lc = f.get("lab_code")
        if not lc:
            continue
        if lc not in by_lab:
            by_lab[lc] = {"total": 0, "provision": 0, "destroy": 0, "top_error": ""}
        by_lab[lc]["total"] += 1
        if f["type"] == "provision":
            by_lab[lc]["provision"] += 1
        else:
            by_lab[lc]["destroy"] += 1
        if not by_lab[lc]["top_error"]:
            by_lab[lc]["top_error"] = f.get("failing_task", "")

    success_rate = round(successful / max(total_jobs, 1) * 100, 1)
    prov_rate = round(provision_success / max(provision_total, 1) * 100, 1) if provision_total > 0 else 0

    result = {
        "summary": {
            "total_jobs": total_jobs,
            "successful": successful,
            "failed": failed,
            "running": running,
            "success_rate": success_rate,
            "provision_sli": prov_rate,
            "provision_sli_target": 93.0,
            "sli_met": prov_rate >= 93.0,
            "failed_24h": len(all_failures),
        },
        "top_errors": by_error[:20],
        "by_cluster": by_cluster,
        "by_lab": by_lab,
        "recent_failures": sorted(all_failures, key=lambda x: x.get("finished") or "", reverse=True)[:50],
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    _cache["data"] = result
    _cache["ts"] = time.time()
    try:
        from api.contracts import record_source_fetch
        record_source_fetch("aap")
    except Exception:
        pass
    return result


def _fetch_jobs(controller: Dict, query: str) -> List[Dict]:
    """Fetch jobs from AAP API."""
    ctx = _make_ssl_ctx()

    auth = base64.b64encode(f"{controller['user']}:{controller['password']}".encode()).decode()
    url = f"{controller['url']}/api/v2/jobs/?{query}"
    from urllib.parse import urlparse
    orig_host = urlparse(controller['url']).hostname

    all_results = []
    while url and len(all_results) < 500:
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        data = json.loads(resp.read())
        all_results.extend(data.get("results", []))
        url = data.get("next")
        if url and not url.startswith("http"):
            url = f"{controller['url']}{url}"
        elif url:
            if urlparse(url).hostname != orig_host:
                logger.warning("AAP pagination URL host mismatch: %s vs %s, stopping", urlparse(url).hostname, orig_host)
                break

    return all_results


def _fetch_job_events(controller: Dict, job_id: int) -> List[Dict]:
    """Fetch failed task events for a specific job."""
    ctx = _make_ssl_ctx()
    auth = base64.b64encode(f"{controller['user']}:{controller['password']}".encode()).decode()
    url = f"{controller['url']}/api/v2/jobs/{job_id}/job_events/?event=runner_on_failed&page_size=3"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        data = json.loads(resp.read())
        return data.get("results", [])
    except Exception:
        return []


def _fetch_job_counts(controller: Dict, cutoff: str) -> Dict:
    """Fetch job count summaries from AAP API."""
    ctx = _make_ssl_ctx()
    auth = base64.b64encode(f"{controller['user']}:{controller['password']}".encode()).decode()

    counts = {"total": 0, "successful": 0, "failed": 0, "running": 0, "provision_total": 0, "provision_success": 0}
    for status in ["successful", "failed", "running"]:
        try:
            url = f"{controller['url']}/api/v2/jobs/?status={status}&finished__gt={cutoff}&page_size=1"
            if status == "running":
                url = f"{controller['url']}/api/v2/jobs/?status=running&page_size=1"
            req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
            resp = urllib.request.urlopen(req, timeout=15, context=ctx)
            data = json.loads(resp.read())
            count = data.get("count", 0)
            counts[status] = count
            counts["total"] += count
        except Exception:
            pass

    try:
        url = f"{controller['url']}/api/v2/jobs/?finished__gt={cutoff}&name__contains=provision&page_size=1"
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        data = json.loads(resp.read())
        counts["provision_total"] = data.get("count", 0)

        url = f"{controller['url']}/api/v2/jobs/?finished__gt={cutoff}&name__contains=provision&status=successful&page_size=1"
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        data = json.loads(resp.read())
        counts["provision_success"] = data.get("count", 0)
    except Exception:
        pass

    return counts
