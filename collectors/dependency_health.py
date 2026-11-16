"""External dependency health monitoring — watch what provisions depend on.

Validated by the Oct 14 / Oct 21-22 2026 incidents: sso.redhat.com and
api.openshift.com returned 5xx and the Assisted Installer integration
crashed calling response.json() on HTML error pages — 546+ provision
failures on Oct 14 alone. StarGate saw the downstream failures
(assisted_installer_failed, json_decode_error) but nothing watched the
dependency itself; the root cause was only identified from Billy's
90-day analysis (Confluence 511804406).

Probe semantics (chosen for these dependencies):
- 2xx/3xx/4xx → PASS. A 403/404 on a base URL is normal — the service
  answered. What broke provisions was 5xx.
- 5xx         → FAIL, external_dependency_5xx. The exact Oct 21 signature.
- unreachable/timeout → FAIL, external_dependency_unreachable.
- slow        → WARN, external_dependency_slow.

Results persist as evaluations (stage dependency-health) with
cluster_name = dependency host — degradation becomes a trend through
dashboards, MTTR, event bus, and change correlation. The Oct-21-style
incident becomes: dependency fails at T, provisions fail at T+minutes,
correlation names the cause instead of chasing symptoms.

Targets: STARGATE_DEPENDENCY_HEALTH_TARGETS (JSON list of
{"name", "url", "timeout_seconds"?, "expected_max_status"?}). Defaults
cover the documented incident dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.dependency_health")

SLOW_WARN_SECONDS = float(os.environ.get("STARGATE_DEPENDENCY_HEALTH_SLOW_SECONDS", "10"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("STARGATE_DEPENDENCY_HEALTH_TIMEOUT_SECONDS", "15"))
DEFAULT_INTERVAL_SECONDS = int(os.environ.get("STARGATE_DEPENDENCY_HEALTH_INTERVAL_SECONDS", "300"))

# The documented-incident dependencies (Billy's 90-day analysis, Oct 21):
# sso.redhat.com and api.openshift.com returned 5xx and crashed the AI
# integration. registry.redhat.io auth failures appear in the OADP RCA.
DEFAULT_TARGETS = [
    {"name": "sso.redhat.com", "url": "https://sso.redhat.com/"},
    {"name": "api.openshift.com", "url": "https://api.openshift.com/"},
    {"name": "registry.redhat.io", "url": "https://registry.redhat.io/"},
]

_health_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL = 120

# Some dependencies present differently to non-browser clients; a plain
# context avoids cert-verification failures on endpoints that serve
# intermediate chains. Verification stays ON — only the check is standard.
_SSL_CONTEXT = ssl.create_default_context()


def _env_derived_targets() -> List[Dict[str, Any]]:
    """Ecosystem services whose URLs the deployment already carries.

    Probing them here (in addition to their collectors) gives the same
    Oct-21-style trend: a service degrading becomes an evaluation trail,
    not a surprise. Each appears only when its env var is set.
    """
    targets: List[Dict[str, Any]] = []

    def _add(name: str, url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if url:
            targets.append({"name": name, "url": url, "timeout_seconds": timeout})

    _add("labagator", os.environ.get("STARGATE_LABAGATOR_URL", "").rstrip("/"))
    _add("demolition", os.environ.get("STARGATE_DEMOLITION_URL", "").rstrip("/"))
    # the MaaS/LLM gateway itself (origin of the LiteLLM URL — model
    # endpoints are already covered by the LLM health loop)
    litellm = os.environ.get("STARGATE_LITELLM_URL", "")
    if litellm:
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(litellm)
            _add("maas-gateway", f"{parts.scheme}://{parts.netloc}/")
        except ValueError:
            pass
    _add("sandbox-api", os.environ.get("STARGATE_SANDBOX_API_URL", "").rstrip("/"))
    if not os.environ.get("STARGATE_SANDBOX_API_URL"):
        _add("sandbox-api-metrics", os.environ.get(
            "STARGATE_SANDBOX_API_METRICS_URL", "").rstrip("/"))
    return [t for t in targets if t["url"]]


def _extra_targets() -> List[Dict[str, Any]]:
    """STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS — a JSON list appended to
    the probe set (rotation-sheet SaaS endpoints, internal services, etc).
    Each entry: {"name", "url", "timeout_seconds"?, "expected_max_status"?}.
    """
    raw = os.environ.get("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS", "")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [t for t in parsed if isinstance(t, dict) and t.get("url")]
        logger.warning("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS is not a JSON list — ignored")
    except json.JSONDecodeError:
        logger.warning("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS is not valid JSON — ignored")
    return []


def _targets() -> List[Dict[str, Any]]:
    raw = os.environ.get("STARGATE_DEPENDENCY_HEALTH_TARGETS", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return parsed
            if isinstance(parsed, list):
                return []  # explicit empty list disables default probing
        except json.JSONDecodeError:
            logger.warning("STARGATE_DEPENDENCY_HEALTH_TARGETS is not valid JSON — using defaults")
        return DEFAULT_TARGETS
    # defaults + env-derived ecosystem services + configured extras,
    # deduplicated by name (an explicit entry always wins)
    combined = DEFAULT_TARGETS + _env_derived_targets() + _extra_targets()
    merged: List[Dict[str, Any]] = []
    for t in combined:  # later entries (extras) override earlier by name
        name = t.get("name") or t.get("url", "?")
        for i, existing in enumerate(merged):
            if (existing.get("name") or existing.get("url", "?")) == name:
                merged[i] = t
                break
        else:
            merged.append(t)
    return merged


def _probe(target: Dict[str, Any]) -> Dict[str, Any]:
    """One GET against one dependency."""
    name = target.get("name") or target.get("url", "?")
    url = target.get("url", "")
    timeout = float(target.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    started = time.monotonic()
    status: Optional[int] = None
    error: Optional[str] = None
    try:
        req = urllib.request.Request(url, method="GET", headers={
            "User-Agent": "stargate-dependency-health/1.0",
            "Accept": "text/html,application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            status = resp.status
            resp.read(2048)  # drain a small body; we only care about status
    except urllib.error.HTTPError as e:
        status = e.code  # an HTTP error IS an answer — the service is up
    except (urllib.error.URLError, ssl.SSLError, OSError, TimeoutError) as e:
        error = str(e)[:200]
    elapsed = time.monotonic() - started
    probed_at = datetime.now(timezone.utc).isoformat()

    if error is not None:
        outcome, failure_class = "fail", "external_dependency_unreachable"
        message = f"unreachable: {error[:120]}"
    elif status is not None and status >= 500:
        outcome, failure_class = "fail", "external_dependency_5xx"
        message = f"HTTP {status} — the Oct-21 signature (dependency erroring)"
    elif status is not None and elapsed > SLOW_WARN_SECONDS:
        outcome, failure_class = "warn", "external_dependency_slow"
        message = f"HTTP {status} in {elapsed:.1f}s (slow)"
    else:
        outcome, failure_class = "pass", None
        message = f"HTTP {status} in {elapsed:.1f}s"

    return {
        "dependency": name,
        "url": url,
        "outcome": outcome,
        "failure_class": failure_class,
        "http_status": status,
        "latency_seconds": round(elapsed, 2),
        "message": message,
        "error": error,
        "probed_at": probed_at,
    }


def probe_dependencies(force: bool = False) -> Dict[str, Any]:
    """Probe all configured external dependencies. Cached briefly."""
    now = time.time()
    if not force and _health_cache["data"] and now - _health_cache["ts"] < _CACHE_TTL:
        return _health_cache["data"]

    results = [_probe(t) for t in _targets()]
    fails = [r for r in results if r["outcome"] == "fail"]
    warns = [r for r in results if r["outcome"] == "warn"]
    report = {
        "dependencies_probed": len(results),
        "passing": len(results) - len(fails) - len(warns),
        "warned": len(warns),
        "failing": len(fails),
        "failing_dependencies": sorted(r["dependency"] for r in fails),
        "slow_dependencies": sorted(r["dependency"] for r in warns),
        "results": results,
        "slow_threshold_seconds": SLOW_WARN_SECONDS,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "5xx and unreachable are the provision-breaking signatures "
            "(validated by the Oct 14/21 2026 SSO incidents). 4xx on a base "
            "URL is normal — the service answered."
        ),
    }
    _health_cache["data"] = report
    _health_cache["ts"] = now
    return report


def run_health_check(db, force: bool = False) -> Dict[str, Any]:
    """Probe, record evaluations, and emit degradation events.

    Shared by the dashboard endpoint and the scheduled loop.
    """
    report = probe_dependencies(force=force)
    try:
        recorded = record_probe_evaluations(report, db)
    except Exception:  # noqa: BLE001 — recording must never break the probe
        logger.exception("dependency-health evaluation recording failed")
        recorded = 0

    if report.get("failing"):
        from events.models import Event as StarGateEvent
        from api.routers._shared import _event_bus

        recent = {
            (e.metadata or {}).get("dependency")
            for e in _event_bus.history
            if e.event_type == "external_dependency_degraded"
        }
        for dep in report["failing_dependencies"]:
            if dep in recent:
                continue
            entry = next(r for r in report["results"] if r["dependency"] == dep)
            _event_bus.emit(StarGateEvent(
                event_type="external_dependency_degraded",
                cluster_name=dep,
                outcome="fail",
                failure_class=entry.get("failure_class"),
                priority=8.0 if entry.get("failure_class") == "external_dependency_5xx" else 7.0,
                message=f"External dependency {dep} degraded: {entry['message']}",
                metadata={
                    "dependency": dep,
                    "url": entry.get("url"),
                    "http_status": entry.get("http_status"),
                    "remediation": (
                        "External dependency failing — provisions using it will fail "
                        "downstream with misleading symptoms (validated: the Oct 21 SSO "
                        "5xx crashed the Assisted Installer as json decode errors). "
                        "Do NOT chase downstream failure classes; check the dependency's "
                        "status page and re-probe. Retrying provisions while it is down "
                        "will not help."
                    ),
                },
            ))

    report["evaluations_recorded"] = recorded
    return report


def record_probe_evaluations(report: Dict[str, Any], db) -> int:
    """Persist probe results as evaluations (stage: dependency-health)."""
    from db.models import EvaluationRecord

    recorded = 0
    for r in report.get("results", []):
        run_id = f"dep-health-{r['dependency']}-{r['probed_at'][:13]}"
        exists = (
            db.query(EvaluationRecord)
            .filter(
                EvaluationRecord.run_id == run_id,
                EvaluationRecord.cluster_name == r["dependency"],
            )
            .first()
        )
        if exists:
            continue
        db.add(EvaluationRecord(
            run_id=run_id,
            stage_id="dependency-health",
            outcome=r["outcome"],
            failure_class=r.get("failure_class"),
            message=r["message"],
            evaluated_at=datetime.now(timezone.utc),
            lab_code="(dependency)",
            cluster_name=r["dependency"],
        ))
        recorded += 1
    if recorded:
        db.commit()
    return recorded
