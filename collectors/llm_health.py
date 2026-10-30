"""LLM gateway health monitoring — LiteLLM-native health, recorded as evaluations.

The platform's inference layer (LiteLLM gateways serving qwen/granite/llama
models on racmaas and maas-rhdp) is a critical dependency with no monitoring.
Documented degradation: 'granite endpoint on maas-rhdp degraded (28s+
timeouts)'. Live-found during build (Oct 30 2026, racmaas): 6 of 15 model
endpoints unhealthy — the entire Gaudi pool (3x gpt-oss-120b), qwen3-235b,
and two stale qwen3-14b-ny-* deployments — silently.

Design (reviewed against LiteLLM's native interfaces):

- PRIMARY: the gateway's own `GET /health` endpoint. LiteLLM probes every
  deployed model server-side and reports healthy_endpoints /
  unhealthy_endpoints with the underlying api_base and error. This is
  authoritative — it sees deployments and replicas the client cannot.
  (Takes ~20-30s on a full gateway; cached here, generous timeout.)
- CROSS-CHECK: `GET /v1/models` — a model advertised but with zero healthy
  endpoints is a fully-broken model group (worse than partial degradation).
- Prometheus `/metrics` (real-traffic latency and error rates per model)
  would be the ideal passive signal but is NOT enabled on the current
  deployments — enabling it is a recommendation, not a prerequisite.
- FALLBACK: if `/health` is unavailable (older LiteLLM), synthetic minimal
  completions per advertised model.

Results are recorded as evaluations (stage_id='model-endpoint-ready' — an
existing pipeline stage) so they flow through the standard machinery:
dashboards, MTTR, event bus, correlation, change attribution. cluster_name
carries the gateway name, lab_code the model id.

Targets: STARGATE_LLM_HEALTH_TARGETS (JSON list of {"name", "url",
"api_key_env"}); the primary gateway from STARGATE_LITELLM_URL/KEY is
included automatically when configured.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("stargate.llm_health")

SLOW_WARN_SECONDS = float(os.environ.get("STARGATE_LLM_HEALTH_SLOW_SECONDS", "10"))
PROBE_TIMEOUT_SECONDS = float(os.environ.get("STARGATE_LLM_HEALTH_TIMEOUT_SECONDS", "45"))
HEALTH_TIMEOUT_SECONDS = float(os.environ.get("STARGATE_LLM_HEALTH_ENDPOINT_TIMEOUT", "60"))

_health_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL = 300


def _targets() -> List[Dict[str, str]]:
    """Gateway targets: explicit config + the primary LiteLLM gateway."""
    targets: List[Dict[str, str]] = []
    raw = os.environ.get("STARGATE_LLM_HEALTH_TARGETS", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                targets.extend(t for t in parsed if t.get("url"))
        except json.JSONDecodeError:
            logger.warning("STARGATE_LLM_HEALTH_TARGETS is not valid JSON — ignoring")
    primary_url = os.environ.get("STARGATE_LITELLM_URL", "")
    primary_key = os.environ.get("STARGATE_LITELLM_API_KEY", "")
    if primary_url and primary_key:
        base = primary_url.split("/v1/")[0] if "/v1/" in primary_url else primary_url.rstrip("/")
        if not any(
            t["url"].rstrip("/").startswith(base) or base.startswith(t["url"].rstrip("/"))
            for t in targets
        ):
            targets.append({"name": "primary", "url": base, "api_key": primary_key})
    return targets


def _resolve_key(target: Dict[str, str]) -> str:
    if target.get("api_key"):
        return target["api_key"]
    env_name = target.get("api_key_env", "")
    return os.environ.get(env_name, "") if env_name else ""


def _api(
    target: Dict[str, str], path: str, payload: Optional[Dict] = None, timeout: float = PROBE_TIMEOUT_SECONDS
) -> Tuple[Optional[int], Any]:
    """GET or POST a gateway path. Returns (status_code, parsed_body_or_None)."""
    key = _resolve_key(target)
    url = target["url"].rstrip("/") + path
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url, data=data, method="POST" if payload else "GET",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return e.code, None
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return None, {"error": str(e)}


def _strip_prefix(model_id: str) -> str:
    """LiteLLM health reports 'openai/granite-2b-cpu'; the public id is the tail."""
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def _gateway_via_native_health(target: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
    """Probe one gateway via its native /health endpoint. None if unavailable."""
    started = time.monotonic()
    status, body = _api(target, "/health", timeout=HEALTH_TIMEOUT_SECONDS)
    elapsed = time.monotonic() - started
    if status != 200 or not isinstance(body, dict) or "healthy_endpoints" not in body:
        return None  # native health unavailable — caller falls back to synthetic

    results: List[Dict[str, Any]] = []
    gateway = target.get("name", target["url"])
    probed_at = datetime.now(timezone.utc).isoformat()

    for e in body.get("healthy_endpoints", []):
        results.append({
            "gateway": gateway,
            "model": _strip_prefix(str(e.get("model", "?"))),
            "api_base": e.get("api_base", ""),
            "outcome": "pass",
            "failure_class": None,
            "latency_seconds": None,
            "message": "healthy (native LiteLLM health check)",
            "error": None,
            "probed_at": probed_at,
        })
    for e in body.get("unhealthy_endpoints", []):
        err = str(e.get("error", ""))[:200]
        results.append({
            "gateway": gateway,
            "model": _strip_prefix(str(e.get("model", "?"))),
            "api_base": e.get("api_base", ""),
            "outcome": "fail",
            "failure_class": "model_endpoint_error",
            "latency_seconds": None,
            "message": f"unhealthy: {err[:120]}",
            "error": err,
            "probed_at": probed_at,
        })

    # Cross-check: models advertised in /v1/models with zero healthy endpoints.
    advertised = set()
    m_status, m_body = _api(target, "/v1/models")
    if m_status == 200 and isinstance(m_body, dict):
        advertised = {_strip_prefix(m.get("id", "")) for m in m_body.get("data", []) if m.get("id")}
    healthy_models = {r["model"] for r in results if r["outcome"] == "pass"}
    reported_models = {r["model"] for r in results}
    for model in sorted(advertised - reported_models):
        results.append({
            "gateway": gateway,
            "model": model,
            "api_base": "",
            "outcome": "fail",
            "failure_class": "model_removed",
            "latency_seconds": None,
            "message": "advertised in /v1/models but absent from /health — deployment missing",
            "error": None,
            "probed_at": probed_at,
        })

    results.append({
        "gateway": gateway,
        "model": "(gateway)",
        "api_base": target["url"],
        "outcome": "pass",
        "failure_class": None,
        "latency_seconds": round(elapsed, 1),
        "message": f"gateway healthy; native health check took {elapsed:.1f}s",
        "error": None,
        "probed_at": probed_at,
    })
    return results


def _probe_model_synthetic(target: Dict[str, str], model: str) -> Dict[str, Any]:
    """Fallback: minimal completion against one model (older LiteLLM without /health)."""
    started = time.monotonic()
    status, body = _api(target, "/v1/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 5,
    })
    elapsed = time.monotonic() - started
    gateway = target.get("name", target["url"])
    probed_at = datetime.now(timezone.utc).isoformat()

    if status == 200 and isinstance(body, dict) and body.get("choices"):
        outcome = "warn" if elapsed > SLOW_WARN_SECONDS else "pass"
        return {
            "gateway": gateway, "model": model, "api_base": "", "outcome": outcome,
            "failure_class": "model_endpoint_slow" if outcome == "warn" else None,
            "latency_seconds": round(elapsed, 2), "message": f"{elapsed:.1f}s completion (synthetic)",
            "error": None, "probed_at": probed_at,
        }
    err = ""
    if isinstance(body, dict):
        e = body.get("error", {})
        err = (e.get("message") if isinstance(e, dict) else str(e)) or ""
    return {
        "gateway": gateway, "model": model, "api_base": "", "outcome": "fail",
        "failure_class": "model_endpoint_error", "latency_seconds": round(elapsed, 2),
        "message": f"HTTP {status or 'unreachable'}: {err[:120] or 'no response'}",
        "error": err[:200], "probed_at": probed_at,
    }


def probe_gateways(force: bool = False) -> Dict[str, Any]:
    """Probe all configured gateways. Native /health first, synthetic fallback.

    Cached; the API layer records results as evaluations and emits events.
    """
    now = time.time()
    if not force and _health_cache["data"] and now - _health_cache["ts"] < _CACHE_TTL:
        return _health_cache["data"]

    results: List[Dict[str, Any]] = []
    mode_by_gateway: Dict[str, str] = {}
    for target in _targets():
        native = _gateway_via_native_health(target)
        if native is not None:
            results.extend(native)
            mode_by_gateway[target.get("name", target["url"])] = "native"
            continue
        # Fallback: synthetic per-model probes against advertised models.
        name = target.get("name", target["url"])
        mode_by_gateway[name] = "synthetic"
        m_status, m_body = _api(target, "/v1/models")
        if m_status == 200 and isinstance(m_body, dict):
            for m in m_body.get("data", []):
                if m.get("id"):
                    results.append(_probe_model_synthetic(target, m["id"]))
        else:
            results.append({
                "gateway": name, "model": "(gateway)", "api_base": target["url"],
                "outcome": "fail", "failure_class": "model_endpoint_error",
                "latency_seconds": None,
                "message": f"gateway unreachable: HTTP {m_status}",
                "error": str(m_body)[:200] if m_body else "no response",
                "probed_at": datetime.now(timezone.utc).isoformat(),
            })

    fails = [r for r in results if r["outcome"] == "fail"]
    warns = [r for r in results if r["outcome"] == "warn"]
    report = {
        "gateways": mode_by_gateway,
        "models_probed": len(results),
        "passing": len(results) - len(fails) - len(warns),
        "warned": len(warns),
        "failing": len(fails),
        "failing_models": sorted({f"{r['gateway']}/{r['model']}" for r in fails}),
        "slow_models": sorted({f"{r['gateway']}/{r['model']}" for r in warns}),
        "results": results,
        "slow_threshold_seconds": SLOW_WARN_SECONDS,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Primary signal is the gateway's native LiteLLM /health (server-side "
            "per-endpoint probes). Prometheus /metrics (real-traffic latency per "
            "model) is not enabled on current deployments — enabling it would add "
            "passive load-aware signal."
        ),
    }
    _health_cache["data"] = report
    _health_cache["ts"] = now
    return report


def record_probe_evaluations(report: Dict[str, Any], db) -> int:
    """Persist probe results as evaluations (stage: model-endpoint-ready).

    All outcomes recorded — the history is what makes degradation visible
    as a trend rather than a snapshot.
    """
    from db.models import EvaluationRecord

    recorded = 0
    for r in report.get("results", []):
        run_id = f"llm-health-{r['gateway']}-{r['probed_at'][:13]}"
        exists = (
            db.query(EvaluationRecord)
            .filter(
                EvaluationRecord.run_id == run_id,
                EvaluationRecord.lab_code == r["model"],
            )
            .first()
        )
        if exists:
            continue
        db.add(EvaluationRecord(
            run_id=run_id,
            stage_id="model-endpoint-ready",
            outcome=r["outcome"],
            failure_class=r.get("failure_class"),
            message=r["message"],
            evaluated_at=datetime.now(timezone.utc),
            lab_code=r["model"],
            cluster_name=r["gateway"],
        ))
        recorded += 1
    if recorded:
        db.commit()
    return recorded
