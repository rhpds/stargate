"""Instrumented LLM call wrapper — captures tokens, latency, cost, errors."""

import hashlib
import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request as urllib_req
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from api.resilience import CircuitBreaker
from api.metrics import llm_calls_total, llm_call_duration, llm_tokens_total

logger = logging.getLogger("stargate.llm")

LLM_URL = os.environ.get(
    "STARGATE_LITELLM_URL",
    "",
)
LLM_API_KEY = os.environ.get("STARGATE_LITELLM_API_KEY", "")
if not LLM_API_KEY:
    logger.warning("STARGATE_LITELLM_API_KEY not set — LLM calls will fail")
LLM_MODEL = os.environ.get("STARGATE_LLM_MODEL", "granite-3-2-8b-instruct")
SSL_VERIFY = os.environ.get("STARGATE_SSL_VERIFY", "true").lower() != "false"

COST_PER_1K_PROMPT = float(os.environ.get("STARGATE_LLM_COST_PROMPT", "0.003"))
COST_PER_1K_COMPLETION = float(os.environ.get("STARGATE_LLM_COST_COMPLETION", "0.006"))

_circuit = CircuitBreaker(failure_threshold=5, cooldown_seconds=60, name="llm")

_prompt_cache: Dict[str, Dict] = {}
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def load_prompt(name: str) -> Dict:
    """Load a versioned prompt from prompts/{name}.yaml."""
    if name in _prompt_cache:
        return _prompt_cache[name]
    import yaml
    path = os.path.join(PROMPTS_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        logger.warning(f"Prompt file not found: {path}")
        return {}
    with open(path) as f:
        prompt = yaml.safe_load(f)
    _prompt_cache[name] = prompt
    logger.info(f"Loaded prompt '{name}' v{prompt.get('version', '?')}")
    return prompt


def load_prompt_with_variants(name: str, prompts_dir: Optional[str] = None) -> Dict:
    """Load a prompt with optional A/B variant selection.

    Checks STARGATE_PROMPT_VARIANTS_{NAME} env var for weighted variant config.
    Format: "1.0:80,1.1:20" (version:weight pairs).
    If not set, loads the default prompt.
    """
    import random
    import yaml
    pdir = prompts_dir or PROMPTS_DIR
    env_key = f"STARGATE_PROMPT_VARIANTS_{name.upper().replace('-', '_')}"
    variants_str = os.environ.get(env_key)

    if not variants_str:
        path = os.path.join(pdir, f"{name}.yaml")
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            return yaml.safe_load(f)

    pairs = []
    for item in variants_str.split(","):
        parts = item.strip().split(":")
        if len(parts) == 2:
            version = parts[0].strip()
            weight = int(parts[1].strip())
            pairs.append((version, weight))

    if not pairs:
        path = os.path.join(pdir, f"{name}.yaml")
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            return yaml.safe_load(f)

    total_weight = sum(w for _, w in pairs)
    roll = random.randint(1, max(total_weight, 1))
    cumulative = 0
    selected_version = pairs[0][0]
    for version, weight in pairs:
        cumulative += weight
        if roll <= cumulative:
            selected_version = version
            break

    default_version = None
    default_path = os.path.join(pdir, f"{name}.yaml")
    if os.path.exists(default_path):
        with open(default_path) as f:
            default_data = yaml.safe_load(f)
            default_version = default_data.get("version")
        if selected_version == default_version:
            return default_data

    variant_path = os.path.join(pdir, f"{name}-v{selected_version}.yaml")
    if os.path.exists(variant_path):
        with open(variant_path) as f:
            return yaml.safe_load(f)

    if os.path.exists(default_path):
        with open(default_path) as f:
            return yaml.safe_load(f)
    return {}


def call_llm(
    endpoint: str,
    messages: List[Dict],
    max_tokens: int = 300,
    temperature: float = 0.1,
    timeout: int = 30,
    context: Optional[Dict] = None,
    db: Optional[Session] = None,
    prompt_version: Optional[str] = None,
) -> Dict:
    ctx = context or {}

    if not LLM_URL:
        return {
            "content": "", "success": False, "metric_id": None, "latency_ms": 0,
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "cost_estimate": None},
            "finish_reason": None, "error": "STARGATE_LITELLM_URL not configured",
        }

    prompt_text = json.dumps(messages)
    prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()

    if not _circuit.check():
        return {
            "content": "", "success": False, "metric_id": None, "latency_ms": 0,
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "cost_estimate": None},
            "finish_reason": None, "error": "Circuit open — LLM temporarily unavailable",
        }

    body = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()

    ssl_ctx = ssl.create_default_context()
    if not SSL_VERIFY:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    req = urllib_req.Request(
        LLM_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
    )

    start = time.time()
    success = False
    content = ""
    finish_reason = None
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    error_type = None
    error_message = None

    try:
        resp = urllib_req.urlopen(req, timeout=timeout, context=ssl_ctx)
        llm_data = json.loads(resp.read())

        choices = llm_data.get("choices", [{}])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        finish_reason = choices[0].get("finish_reason") if choices else None

        usage = llm_data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        success = True
        _circuit.record_success()

    except urllib.error.URLError as e:
        error_type = "timeout" if "timed out" in str(e) else "connection_error"
        error_message = str(e)[:500]
        _circuit.record_failure()
        logger.warning(f"LLM call failed ({endpoint}): {error_type} — {error_message}")
    except json.JSONDecodeError as e:
        error_type = "parse_error"
        error_message = str(e)[:500]
        logger.warning(f"LLM response parse failed ({endpoint}): {error_message}")
    except (TimeoutError, ConnectionError, OSError) as e:
        error_type = "network_error"
        error_message = str(e)[:500]
        _circuit.record_failure()
        logger.warning(f"LLM network error ({endpoint}): {error_message}")

    latency_ms = int((time.time() - start) * 1000)

    llm_calls_total.labels(endpoint=endpoint, success=str(success).lower()).inc()
    llm_call_duration.labels(endpoint=endpoint).observe(latency_ms / 1000)
    if prompt_tokens:
        llm_tokens_total.labels(endpoint=endpoint, type="prompt").inc(prompt_tokens)
    if completion_tokens:
        llm_tokens_total.labels(endpoint=endpoint, type="completion").inc(completion_tokens)

    cost_estimate = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost_estimate = (
            (prompt_tokens / 1000) * COST_PER_1K_PROMPT
            + (completion_tokens / 1000) * COST_PER_1K_COMPLETION
        )

    metric_id = None
    if db:
        try:
            from db.models import LLMMetric
            metric = LLMMetric(
                endpoint=endpoint,
                model=LLM_MODEL,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_estimate=cost_estimate,
                latency_ms=latency_ms,
                success=success,
                finish_reason=finish_reason,
                error_type=error_type,
                error_message=error_message,
                prompt_hash=prompt_hash,
                response_preview=content if content else None,
                lab_code=ctx.get("lab_code"),
                cluster_name=ctx.get("cluster_name"),
                failure_class=ctx.get("failure_class"),
                confidence=ctx.get("confidence"),
                prompt_version=prompt_version,
                called_at=datetime.now(timezone.utc),
            )
            db.add(metric)
            db.commit()
            metric_id = metric.id
        except Exception as e:
            logger.warning(f"Failed to persist LLM metric: {e}")

    log_msg = f"LLM {endpoint}: {latency_ms}ms, tokens={total_tokens or '?'}, success={success}"
    if cost_estimate:
        log_msg += f", cost=${cost_estimate:.4f}"
    logger.info(log_msg)

    return {
        "content": content,
        "success": success,
        "metric_id": metric_id,
        "latency_ms": latency_ms,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_estimate": cost_estimate,
        },
        "finish_reason": finish_reason,
        "error": error_message if not success else None,
    }
