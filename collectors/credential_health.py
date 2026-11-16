"""Credential health — prove the credentials StarGate depends on still work.

The 2026 Turkey Vulture rotation (GPTEINFRA-18544) exposed the gap this fills:
reachability probes call a 401 a pass, nothing tracks expiry, and a credential
rotated in one place can stay dead in another with no signal. Every credential
here is exercised against its own service, and the result is a normal
evaluation — so it gets history, a trend, and a failure class.

Failure classes:
  credential_missing     — configured but not present where expected
  credential_rejected    — the service refused the credential (401/403)
  credential_unreachable — the service could not be contacted
  credential_expiring    — works, but expires inside the warn window

Outcomes are pass / warn / fail, matching the rest of the platform.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.credential_health")

DEFAULT_INTERVAL_SECONDS = int(
    os.environ.get("STARGATE_CREDENTIAL_HEALTH_INTERVAL_SECONDS", "900")
)
EXPIRY_WARN_DAYS = int(os.environ.get("STARGATE_CREDENTIAL_EXPIRY_WARN_DAYS", "90"))
# A JWT with no `exp` never expires — that is the legacy-token failure mode
# behind the 2026 rotation (icinga-ro-token, cluster-scheduler-token).
# Waive deliberately, per credential name, or it fails the gate.
EXPIRY_WAIVERS = {
    value.strip()
    for value in os.environ.get("STARGATE_CREDENTIAL_EXPIRY_WAIVERS", "").split(",")
    if value.strip()
}
PROBE_TIMEOUT_SECONDS = float(
    os.environ.get("STARGATE_CREDENTIAL_HEALTH_TIMEOUT_SECONDS", "10")
)

_health_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL = 120


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_jwt(token: str) -> bool:
    """True when the value is a JWT (three dot-separated parts)."""
    return bool(token) and token.count(".") == 2


def _jwt_expiry(token: str) -> Optional[datetime]:
    """Return the exp claim of a JWT, or None for opaque/long-lived tokens."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return datetime.fromtimestamp(exp, timezone.utc) if exp else None
    except Exception:
        return None


def _read_token(kubeconfig_path: Path) -> Optional[str]:
    try:
        text = kubeconfig_path.read_text()
    except OSError:
        return None
    match = re.search(r"token:\s*(\S+)", text)
    return match.group(1) if match else None


def _result(
    name: str,
    kind: str,
    source: str,
    outcome: str,
    status: Optional[int] = None,
    failure_class: Optional[str] = None,
    message: str = "",
    expires_at: Optional[datetime] = None,
    ms: Optional[int] = None,
) -> Dict[str, Any]:
    days_left = None
    if expires_at:
        days_left = max(0, (expires_at - _now()).days)
    return {
        "credential": name,
        "kind": kind,
        "source": source,
        "outcome": outcome,
        "status": status,
        "failure_class": failure_class,
        "message": message,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "days_left": days_left,
        "ms": ms,
        "probed_at": _now().isoformat(),
    }


# ---------------------------------------------------------------------------
# probes
# ---------------------------------------------------------------------------

def _probe_kubeconfig(name: str, path: Path) -> Dict[str, Any]:
    source = f"secrets/{path.name}"
    if not path.exists():
        return _result(name, "kubeconfig", source, "fail",
                       failure_class="credential_missing",
                       message=f"no kubeconfig at {path}")

    token = _read_token(path)
    expires_at = _jwt_expiry(token) if token else None

    oc = shutil.which("oc")
    if not oc:
        return _result(name, "kubeconfig", source, "unknown",
                       message="oc not available on PATH", expires_at=expires_at)

    started = time.time()
    try:
        proc = subprocess.run(
            [oc, "whoami"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
            env={**os.environ, "KUBECONFIG": str(path)},
        )
        ms = int((time.time() - started) * 1000)
        who = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return _result(name, "kubeconfig", source, "fail",
                       failure_class="credential_unreachable",
                       message="timed out contacting the API server", expires_at=expires_at)
    except Exception as exc:  # noqa: BLE001 — a probe must never break the loop
        return _result(name, "kubeconfig", source, "fail",
                       failure_class="credential_unreachable",
                       message=type(exc).__name__, expires_at=expires_at)

    if who:
        outcome, failure_class = "pass", None
        if token and _is_jwt(token) and expires_at is None and name not in EXPIRY_WAIVERS:
            outcome, failure_class = "fail", "credential_no_expiry"
        elif expires_at and (expires_at - _now()) <= timedelta(days=EXPIRY_WARN_DAYS):
            outcome, failure_class = "warn", "credential_expiring"
        return _result(name, "kubeconfig", source, outcome, 200, failure_class,
                       who, expires_at=expires_at, ms=ms)

    lowered = err.lower()
    if "unauthorized" in lowered or "logged in" in lowered or "401" in lowered:
        failure_class, message = "credential_rejected", err[:200] or "rejected"
    elif "forbidden" in lowered:
        failure_class, message = "credential_rejected", err[:200] or "forbidden"
    else:
        failure_class, message = "credential_unreachable", err[:200] or "no identity returned"
    return _result(name, "kubeconfig", source, "fail", None, failure_class,
                   message, expires_at=expires_at, ms=ms)


def _probe_http(
    name: str,
    kind: str,
    source: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    warning: Optional[str] = None,
) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    started = time.time()
    try:
        with urllib.request.urlopen(
            request, timeout=PROBE_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        ) as response:
            ms = int((time.time() - started) * 1000)
            outcome = "warn" if warning else "pass"
            return _result(name, kind, source, outcome, response.status,
                           "credential_expiring" if warning else None,
                           warning or "", ms=ms)
    except urllib.error.HTTPError as exc:
        ms = int((time.time() - started) * 1000)
        if exc.code in (401, 403):
            return _result(name, kind, source, "fail", exc.code,
                           "credential_rejected",
                           f"HTTP {exc.code}", ms=ms)
        return _result(name, kind, source, "warn", exc.code,
                       "credential_unreachable", f"HTTP {exc.code}", ms=ms)
    except Exception as exc:  # noqa: BLE001
        ms = int((time.time() - started) * 1000)
        return _result(name, kind, source, "fail", None,
                       "credential_unreachable", type(exc).__name__, ms=ms)


# ---------------------------------------------------------------------------
# target discovery
# ---------------------------------------------------------------------------

def _kubeconfig_targets() -> List[Dict[str, Any]]:
    from cli.kubeconfigs import resolve_kubeconfig
    from cli.scan import load_clusters

    targets = []
    for cluster, filename in load_clusters().items():
        targets.append({
            "name": f"kubeconfig:{cluster}",
            "probe": lambda c=cluster, f=filename: _probe_kubeconfig(
                f"kubeconfig:{c}", resolve_kubeconfig(c, f)),
        })
    return targets


def _env_targets() -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []

    for name, var in (
        ("github:agnosticv", "STARGATE_AGNOSTICV_TOKEN"),
        ("github:repo-token", "STARGATE_GITHUB_TOKEN"),
    ):
        token = os.environ.get(var, "")
        if token:
            targets.append({
                "name": name,
                "probe": lambda n=name, v=var, t=token: _probe_http(
                    n, "github", v, "https://api.github.com/rate_limit",
                    {"Authorization": f"token {t}", "User-Agent": "stargate-credential-health"},
                ),
            })

    litellm = os.environ.get("STARGATE_LITELLM_URL", "").rstrip("/")
    litellm_key = os.environ.get("STARGATE_LITELLM_API_KEY", "")
    if litellm and litellm_key:
        base = litellm.split("/v1/")[0] if "/v1/" in litellm else litellm
        targets.append({
            "name": "maas:litellm",
            "probe": lambda b=base, k=litellm_key: _probe_http(
                "maas:litellm", "bearer", "STARGATE_LITELLM_API_KEY",
                b + "/v1/models", {"Authorization": f"Bearer {k}"},
            ),
        })

    try:
        for entry in json.loads(os.environ.get("STARGATE_LLM_HEALTH_TARGETS", "[]")):
            url = (entry.get("url") or "").rstrip("/")
            if not url:
                continue
            key = entry.get("api_key", "")
            label = entry.get("name") or url
            targets.append({
                "name": f"llm:{label}",
                "probe": lambda u=url, k=key, n=label: _probe_http(
                    f"llm:{n}", "bearer", "STARGATE_LLM_HEALTH_TARGETS",
                    u + "/v1/models", {"Authorization": f"Bearer {k}"} if k else {},
                ),
            })
    except (json.JSONDecodeError, TypeError):
        logger.warning("STARGATE_LLM_HEALTH_TARGETS is not valid JSON — skipped")

    geolux = os.environ.get("STARGATE_GEOLUX_URL", "").rstrip("/")
    if geolux:
        targets.append({
            "name": "geolux",
            "probe": lambda u=geolux: _probe_http(
                "geolux", "api-key", "STARGATE_GEOLUX_API_KEY", u + "/health",
                {"X-API-Key": os.environ.get("STARGATE_GEOLUX_API_KEY", "")},
            ),
        })

    jira = os.environ.get("STARGATE_JIRA_URL", "").rstrip("/")
    jira_token = os.environ.get("STARGATE_JIRA_TOKEN", "")
    if jira and jira_token:
        email = os.environ.get("STARGATE_JIRA_EMAIL", "")
        basic = base64.b64encode(f"{email}:{jira_token}".encode()).decode()

        def _jira_probe(u=jira, b=basic) -> Dict[str, Any]:
            return _probe_http("jira", "basic", "STARGATE_JIRA_TOKEN",
                               u + "/rest/api/3/myself", {"Authorization": f"Basic {b}"})

        targets.append({"name": "jira", "probe": _jira_probe})

    return targets


def _targets() -> List[Dict[str, Any]]:
    return _kubeconfig_targets() + _env_targets()


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def run_credential_check(db=None, force: bool = False) -> Dict[str, Any]:
    """Probe every configured credential and optionally persist the results."""
    if not force and _health_cache["data"] and (time.time() - _health_cache["ts"]) < _CACHE_TTL:
        return _health_cache["data"]

    results = []
    for target in _targets():
        try:
            results.append(target["probe"]())
        except Exception as exc:  # noqa: BLE001 — one bad probe must not stop the rest
            logger.warning("credential probe %s failed: %s", target.get("name"), exc)

    report = {
        "checked_at": _now().isoformat(),
        "credentials_probed": len(results),
        "failing": sum(1 for r in results if r["outcome"] == "fail"),
        "degraded": sum(1 for r in results if r["outcome"] == "warn"),
        "results": results,
    }
    _health_cache["data"] = report
    _health_cache["ts"] = time.time()

    if db is not None:
        report["evaluations_recorded"] = record_credential_evaluations(report, db)

    return report


def record_credential_evaluations(report: Dict[str, Any], db) -> int:
    """Persist one evaluation per credential (hourly de-duplicated)."""
    from db.models import EvaluationRecord

    recorded = 0
    for r in report.get("results", []):
        run_id = f"cred-health-{r['credential']}-{r['probed_at'][:13]}"
        exists = (
            db.query(EvaluationRecord)
            .filter(
                EvaluationRecord.run_id == run_id,
                EvaluationRecord.cluster_name == r["credential"],
            )
            .first()
        )
        if exists:
            continue
        db.add(EvaluationRecord(
            run_id=run_id,
            stage_id="credential-health",
            outcome=r["outcome"],
            failure_class=r.get("failure_class"),
            message=r.get("message") or "",
            criteria_results=[{
                "kind": r.get("kind"),
                "source": r.get("source"),
                "status": r.get("status"),
                "expires_at": r.get("expires_at"),
                "days_left": r.get("days_left"),
            }],
            evaluated_at=_now(),
            lab_code="(credential)",
            cluster_name=r["credential"],
        ))
        recorded += 1
    if recorded:
        db.commit()
    return recorded
