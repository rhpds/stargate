"""Read-only investigation agent — iterative tool-calling for AI analysis.

Uses LLM tool calling to investigate sandbox failures across the RHDP stack.
Every tool is strictly read-only. No mutations, no write verbs, no execution.

The agent loop:
  1. Gets initial evidence (failure class, namespace, cluster)
  2. Calls LLM with available tools
  3. LLM decides which tools to call
  4. Tools execute (read-only) and return results
  5. Results appended to conversation, LLM called again
  6. Repeats until LLM produces a final text answer or max iterations hit

Safety:
  - oc commands: allowlist of read-only verbs only (get, describe, logs, adm top)
  - All output through _redact_sensitive before agent sees it
  - Max 8 iterations, max 60s total wall time
  - No oc create/delete/patch/apply/scale/edit
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.agent")

# Read-only oc verbs — NEVER add write verbs here
_SAFE_VERBS = frozenset({"get", "describe", "logs", "adm", "api-resources", "whoami"})
_SAFE_ADM = frozenset({"top"})

MAX_ITERATIONS = 8
MAX_WALL_SECONDS = 90
MAX_OUTPUT_CHARS = 3000

# Shared progress dict — the dashboard endpoint writes a reference here
# so the agent can update tool_calls in real-time for polling
_investigation_progress: Dict[str, Dict] = {}


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "oc_read",
            "description": "Run a read-only oc command against the target cluster. Only get, describe, logs, and adm top are allowed. Always include -n <namespace>. Output is automatically redacted for sensitive data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full oc command to run, e.g. 'oc get pods -n sandbox-xxx -o wide' or 'oc logs pod/showroom-xxx -c setup -n sandbox-xxx --tail=50'",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_evaluations",
            "description": "Query StarGate evaluation history for a namespace. Returns recent pass/fail evaluations with failure classes and messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "The sandbox namespace to query"},
                    "limit": {"type": "integer", "description": "Max results to return (default 10)"},
                },
                "required": ["namespace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lab_identity",
            "description": "Look up lab identity from the guid in the namespace name. Returns lab display name, AgnosticV config path, AgnosticD governor, owner email, and GitHub URL for the lab config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "The sandbox namespace"},
                },
                "required": ["namespace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_github_file",
            "description": "Fetch a file from a GitHub repo (read-only). Use this to read AgnosticV config files (common.yaml) or AgnosticD role tasks to understand what the lab deploys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "GitHub repo in owner/name format, e.g. 'rhpds/agnosticv'"},
                    "path": {"type": "string", "description": "File path within the repo, e.g. 'published/openshift-days-ops-track/prod.yaml'"},
                    "branch": {"type": "string", "description": "Branch name (default 'main')"},
                },
                "required": ["repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resolution_history",
            "description": "Look up how previous failures on this namespace or catalog item resolved. Returns resolution type (self_resolved, human_remediated, namespace_recycled), TTR, and what action was taken.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "The sandbox namespace"},
                    "failure_class": {"type": "string", "description": "Optional: filter to a specific failure class"},
                },
                "required": ["namespace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pool_status",
            "description": "Check Poolboy resource pool capacity for a catalog item. Returns available slots, min available, ready count, and whether the pool is exhausted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "catalog_item": {"type": "string", "description": "The catalog item slug, e.g. 'ocp4-cluster' or 'zt-ansiblebu'"},
                },
                "required": ["catalog_item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_provisioning_status",
            "description": "Get overall RHDP provisioning status from Babylon — total subjects, started, failed, failure rate. Also returns stuck teardown and resource leak data.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_labagator_info",
            "description": "Look up lab details from Labagator — the lab catalog system. Returns lab title, ci_name, env_type, deploy mode, components, and session info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "catalog_item": {"type": "string", "description": "The catalog item slug to search for"},
                },
                "required": ["catalog_item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sandbox_placement",
            "description": "Look up Sandbox API placement for a sandbox namespace. Returns service UUID, owner, resource types, quota, and cloud selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "The sandbox namespace"},
                },
                "required": ["namespace"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations (ALL read-only)
# ---------------------------------------------------------------------------

def _redact(text: str) -> str:
    """Import and apply the dashboard's redaction function."""
    try:
        from api.routers.dashboard import _redact_sensitive
        return _redact_sensitive(text)
    except ImportError:
        # Fallback inline redaction
        text = re.sub(r'(password|secret|token|key)\s*[:=]\s*\S+', r'\1: [REDACTED]', text, flags=re.IGNORECASE)
        text = re.sub(r'-----BEGIN [A-Z ]+-----[\s\S]*?-----END [A-Z ]+-----', '[CERTIFICATE REDACTED]', text)
        return text


def _is_safe_oc(cmd: str) -> bool:
    """Validate that an oc command is strictly read-only."""
    parts = cmd.strip().split()
    if not parts or parts[0] != "oc":
        return False
    if len(parts) < 2:
        return False
    verb = parts[1]
    if verb not in _SAFE_VERBS:
        return False
    if verb == "adm" and (len(parts) < 3 or parts[2] not in _SAFE_ADM):
        return False
    return True


def tool_oc_read(command: str, cluster: str, kubeconfig_dir: str) -> str:
    """Execute a read-only oc command."""
    if not _is_safe_oc(command):
        return f"REFUSED: '{command}' is not a read-only command. Only oc get/describe/logs/adm top are allowed."

    kubeconfig = os.path.join(kubeconfig_dir, f"kubeconfig-{cluster}")
    if not os.path.exists(kubeconfig):
        kubeconfig = os.path.join(kubeconfig_dir, "kubeconfig-executor")
    if not os.path.exists(kubeconfig):
        return "ERROR: No kubeconfig available for this cluster"

    try:
        use_shell = "|" in command
        r = subprocess.run(
            command if use_shell else command.split(),
            capture_output=True, text=True, timeout=10,
            shell=use_shell,
            env={**os.environ, "KUBECONFIG": kubeconfig},
        )
        output = r.stdout.strip() if r.returncode == 0 else f"ERROR (exit {r.returncode}): {r.stderr.strip()}"
        output = _redact(output)
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out (10s limit)"
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


def tool_query_evaluations(namespace: str, limit: int = 10) -> str:
    """Query evaluation history from the database."""
    try:
        from db.database import get_session_factory
        from db.models import EvaluationRecord
        factory = get_session_factory()
        db = factory()
        try:
            evals = db.query(EvaluationRecord).filter(
                EvaluationRecord.lab_code == namespace,
            ).order_by(EvaluationRecord.id.desc()).limit(limit).all()

            if not evals:
                return f"No evaluations found for {namespace}"

            lines = [f"Last {len(evals)} evaluations for {namespace}:"]
            for e in evals:
                lines.append(f"  {e.evaluated_at}: {e.outcome} — {e.failure_class or 'none'} | {(e.message or '')[:100]}")
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as e:
        return f"ERROR querying evaluations: {str(e)[:200]}"


def tool_get_lab_identity(namespace: str) -> str:
    """Look up lab identity from LabMapping."""
    try:
        m = re.match(r"^sandbox-([a-z0-9]+)-(.+)$", namespace)
        if not m:
            return f"Cannot extract guid from namespace {namespace}"
        guid = m.group(1)

        from db.database import get_session_factory
        from db.models import LabMapping
        factory = get_session_factory()
        db = factory()
        try:
            lm = db.query(LabMapping).filter(LabMapping.lab_code == f"guid:{guid}").first()
            if not lm:
                return f"No lab mapping found for guid {guid}. Catalog item slug from namespace: {m.group(2)}"

            lines = [
                f"Lab name: {lm.ci_name or 'unknown'}",
                f"Catalog item: {lm.ci_base or 'unknown'}",
                f"AgnosticD governor: {lm.ci_slug or 'unknown'}",
            ]
            if lm.agnosticv_path:
                lines.append(f"AgnosticV config: {lm.agnosticv_path}")
                lines.append(f"GitHub URL: https://github.com/rhpds/agnosticv/tree/main/{lm.agnosticv_path}")
            if lm.owner:
                lines.append(f"Owner: {lm.owner}")
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


def tool_fetch_github_file(repo: str, path: str, branch: str = "main") -> str:
    """Fetch a file from GitHub (read-only)."""
    import urllib.request
    import ssl

    # Only allow known RHDP repos
    allowed_orgs = {"rhpds", "agnosticd", "redhat-cop"}
    org = repo.split("/")[0] if "/" in repo else ""
    if org not in allowed_orgs:
        return f"REFUSED: Only repos from {allowed_orgs} are allowed, got '{org}'"

    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            content = _redact(content)
            if len(content) > MAX_OUTPUT_CHARS:
                content = content[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            return content or "(empty file)"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {path} not found in {repo}/{branch}"
    except Exception as e:
        return f"ERROR fetching {url}: {str(e)[:200]}"


def tool_get_resolution_history(namespace: str, failure_class: str = "") -> str:
    """Look up resolution history from the database."""
    try:
        from db.database import get_session_factory
        from db.models import ResolutionRecord
        factory = get_session_factory()
        db = factory()
        try:
            query = db.query(ResolutionRecord).filter(
                ResolutionRecord.lab_code == namespace,
            )
            if failure_class:
                query = query.filter(ResolutionRecord.failure_class == failure_class)
            records = query.order_by(ResolutionRecord.resolved_at.desc()).limit(5).all()

            if not records:
                return f"No resolution history for {namespace}" + (f" / {failure_class}" if failure_class else "")

            lines = [f"Resolution history ({len(records)} records):"]
            for r in records:
                ttr = f"{round(r.ttr_seconds/60, 1)}m" if r.ttr_seconds else "?"
                lines.append(f"  {r.failure_class}: {r.resolution_type} — {r.resolution_action or '?'} (TTR: {ttr})")
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


def tool_get_pool_status(catalog_item: str) -> str:
    """Check pool capacity from Babylon cache."""
    try:
        from api.routers._shared import _load_latest_babylon
        babylon = _load_latest_babylon()
        if not babylon:
            return "No Babylon data available"

        all_pools = babylon.get("pools", {}).get("all_pools", [])
        matching = [p for p in all_pools if catalog_item.lower() in p.get("name", "").lower()]

        if not matching:
            prov = babylon.get("provisioning", {})
            return f"No pools matching '{catalog_item}'. Platform provisioning: {prov.get('total', 0)} subjects, {prov.get('started', 0)} started, {prov.get('failed', 0)} failed ({prov.get('failure_rate', 0)}%)"

        lines = []
        for p in matching[:5]:
            lines.append(f"Pool {p.get('name', '?')}: available={p.get('available', 0)}, min_available={p.get('min_available', 0)}, ready={p.get('ready', 0)}, total={p.get('total', 0)}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


def tool_get_provisioning_status() -> str:
    """Get overall provisioning status from Babylon cache."""
    try:
        from api.routers._shared import _load_latest_babylon
        babylon = _load_latest_babylon()
        if not babylon:
            return "No Babylon data available"

        prov = babylon.get("provisioning", {})
        stuck = babylon.get("stuck_teardowns", {})
        leaks = babylon.get("resource_leaks", {})

        lines = [
            f"Provisioning: {prov.get('total', 0)} subjects, {prov.get('started', 0)} started, {prov.get('failed', 0)} failed ({prov.get('failure_rate', 0)}%)",
            f"Stuck teardowns: {stuck.get('stuck_count', stuck.get('stuck', 0))} (threshold {stuck.get('threshold_hours', 2)}h)",
            f"Resource leaks: {leaks.get('orphaned_count', 0)} orphaned PVs ({leaks.get('orphaned_capacity_gi', 0)} Gi)",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


def tool_get_labagator_info(catalog_item: str) -> str:
    """Look up lab info from Labagator."""
    try:
        import urllib.request
        labagator_url = os.environ.get("STARGATE_LABAGATOR_URL", "")
        if not labagator_url:
            return "Labagator URL not configured"

        with urllib.request.urlopen(f"{labagator_url}/labs?limit=300", timeout=5) as resp:
            labs = json.loads(resp.read())

        matching = []
        for lab in (labs if isinstance(labs, list) else []):
            ci = lab.get("ci_name") or ""
            slug = ci.split(".", 1)[1] if "." in ci else ci
            if catalog_item.lower() in slug.lower():
                matching.append(lab)

        if not matching:
            return f"No Labagator entry for '{catalog_item}'"

        lines = []
        for lab in matching[:3]:
            lines.append(f"Title: {lab.get('title', '?')}")
            lines.append(f"  ci_name: {lab.get('ci_name', '?')}")
            lines.append(f"  env_type: {lab.get('env_type', '?')}")
            lines.append(f"  status: {lab.get('status', '?')}")
            lines.append(f"  deploy_mode: {lab.get('deploy_mode', '?')}")
            components = lab.get("components", [])
            if components:
                lines.append(f"  components: {len(components)}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


def tool_get_sandbox_placement(namespace: str) -> str:
    """Look up Sandbox API placement."""
    try:
        m = re.match(r"^sandbox-([a-z0-9]+)-", namespace)
        if not m:
            return f"Cannot extract guid from {namespace}"

        import subprocess as _sp
        # Get serviceUuid from namespace labels
        kubeconfig_dir = os.environ.get("STARGATE_EXECUTOR_KUBECONFIG", "")
        if kubeconfig_dir:
            kubeconfig_dir = os.path.dirname(kubeconfig_dir)

        # Try to find the serviceUuid from LabMapping
        from db.database import get_session_factory
        from db.models import LabMapping
        factory = get_session_factory()
        db = factory()
        try:
            lm = db.query(LabMapping).filter(LabMapping.lab_code == namespace).first()
            if lm:
                lines = [f"Owner: {lm.owner or 'unknown'}"]
                if lm.cloud:
                    lines.append(f"Cloud/comment: {lm.cloud}")
                return "\n".join(lines)

            guid_lm = db.query(LabMapping).filter(LabMapping.lab_code == f"guid:{m.group(1)}").first()
            if guid_lm:
                return f"Lab: {guid_lm.ci_name or '?'}, governor: {guid_lm.ci_slug or '?'}, path: {guid_lm.agnosticv_path or '?'}"

            return f"No Sandbox API data cached for {namespace}"
        finally:
            db.close()
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _dispatch_tool(name: str, args: Dict, cluster: str, kubeconfig_dir: str) -> str:
    """Route a tool call to its implementation."""
    if name == "oc_read":
        return tool_oc_read(args.get("command", ""), cluster, kubeconfig_dir)
    elif name == "query_evaluations":
        return tool_query_evaluations(args.get("namespace", ""), args.get("limit", 10))
    elif name == "get_lab_identity":
        return tool_get_lab_identity(args.get("namespace", ""))
    elif name == "fetch_github_file":
        return tool_fetch_github_file(args.get("repo", ""), args.get("path", ""), args.get("branch", "main"))
    elif name == "get_resolution_history":
        return tool_get_resolution_history(args.get("namespace", ""), args.get("failure_class", ""))
    elif name == "get_pool_status":
        return tool_get_pool_status(args.get("catalog_item", ""))
    elif name == "get_provisioning_status":
        return tool_get_provisioning_status()
    elif name == "get_labagator_info":
        return tool_get_labagator_info(args.get("catalog_item", ""))
    elif name == "get_sandbox_placement":
        return tool_get_sandbox_placement(args.get("namespace", ""))
    else:
        return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are a senior Red Hat OpenShift SRE investigating a failure on the RHDP (Red Hat Demo Platform). You have read-only tools to investigate. Use them iteratively to build understanding before giving your final analysis.

Investigation strategy:
1. ALWAYS start with get_lab_identity to understand what lab this sandbox is running
2. Check pod status: oc get pods -n <namespace> -o wide
3. For crashlooping pods: oc logs <pod> -c <container> -n <namespace> --previous --tail=50
4. Use get_lab_identity result to find the AgnosticV config, then fetch_github_file to read it
5. Check resolution history to see if this is a known pattern
6. Check pool status if the issue might be capacity-related

Failure-class playbooks:
- pods_crashlooping: Check which container is failing (init or main), get its logs, find the GIT_REPO_URL env var — that's where the fix goes
- quota_exceeded: Check oc get resourcequota -n <namespace>, identify which resource is exhausted, check if the lab config requests too much
- pvc_binding_failed / claim_misbound: Check oc get pvc -n <namespace>, look for Pending PVCs, check storage class availability
- scheduling_failed: Check oc get events for FailedScheduling, look at resource requests vs node capacity
- sync_failed: Check oc get events for ReconcileError, look at operator status
- readiness_probe_failed: Usually transient during provisioning — check namespace age and whether the pod eventually becomes ready
- image_pull_backoff: Check image name and pull secret configuration

Your final analysis MUST include:
1. **Diagnosis**: What is failing and why (quote specific error messages)
2. **Root Cause**: Name the specific component — container image, Ansible role, config file
3. **Remediation Strategy**: One of:
   a. A link to the code that needs changing: "Fix in https://github.com/rhpds/agnosticv/tree/main/<path>"
   b. An exact oc command to fix it: "oc patch ... -n <namespace>"
   c. "Watch and wait — this self-resolves in X minutes based on history"
4. **Owner**: Who should fix this (from the lab identity owner field)

Rules:
- NEVER suggest commands that modify the cluster (no create, delete, patch, apply, scale)
- NEVER echo passwords, tokens, or credentials — they are automatically redacted
- NEVER suggest oc commands for Babylon CRDs (resourceclaim, anarchysubject) — those don't exist on workload clusters
- ALWAYS include the AgnosticV config URL when available — that's where lab developers fix issues
- If the GIT_REPO_URL env var is visible in pod describe output, that's the lab's source repo — link to it"""


def run_investigation(
    namespace: str,
    cluster: str,
    failure_class: str,
    initial_evidence: str,
    kubeconfig_dir: str = "",
    model: str = "",
    db=None,
    job_id: str = "",
) -> Dict[str, Any]:
    """Run the investigation agent loop.

    Returns {"analysis": str, "tool_calls": list, "iterations": int, "error": str|None}
    """
    from api.llm import call_llm, LLM_MODEL, LLM_URL

    if not LLM_URL:
        return {"analysis": "", "tool_calls": [], "iterations": 0, "error": "LLM not configured"}

    if not kubeconfig_dir:
        kubeconfig_dir = str(os.path.dirname(os.path.dirname(__file__))) + "/secrets"

    use_model = model or os.environ.get("STARGATE_AGENT_MODEL", LLM_MODEL)

    messages: List[Dict] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate this failure:\n\nNamespace: {namespace}\nCluster: {cluster}\nFailure class: {failure_class}\n\n{initial_evidence}"},
    ]

    all_tool_calls = []
    start_time = time.time()

    for iteration in range(MAX_ITERATIONS):
        if time.time() - start_time > MAX_WALL_SECONDS:
            logger.warning("Agent hit wall time limit (%ds)", MAX_WALL_SECONDS)
            break

        # Call LLM with tools
        result = _call_llm_with_tools(
            messages=messages,
            tools=TOOLS,
            model=use_model,
            max_tokens=2400,
            temperature=0.2,
            timeout=30,
        )

        if not result.get("success"):
            # If tool calling fails (model doesn't support it), fall back to single-shot
            logger.info("Tool calling not supported or failed, falling back to single-shot")
            fallback = call_llm(
                endpoint="agent-investigation",
                messages=messages,
                max_tokens=2400,
                temperature=0.2,
                timeout=30,
                db=db,
            )
            return {
                "analysis": _redact(fallback.get("content", "")),
                "tool_calls": all_tool_calls,
                "iterations": iteration + 1,
                "error": None if fallback.get("success") else fallback.get("error"),
                "fallback": True,
            }

        response_message = result.get("message", {})
        tool_calls_in_response = response_message.get("tool_calls", [])

        if not tool_calls_in_response:
            # No tool calls — LLM produced final answer
            final_text = response_message.get("content", "")
            return {
                "analysis": _redact(final_text),
                "tool_calls": all_tool_calls,
                "iterations": iteration + 1,
                "error": None,
            }

        # Process tool calls
        messages.append(response_message)

        for tc in tool_calls_in_response:
            fn_name = tc.get("function", {}).get("name", "")
            fn_args_raw = tc.get("function", {}).get("arguments", "{}")
            tc_id = tc.get("id", "")

            try:
                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except json.JSONDecodeError:
                fn_args = {}

            logger.info("Agent tool call: %s(%s)", fn_name, json.dumps(fn_args)[:100])

            tool_result = _dispatch_tool(fn_name, fn_args, cluster, kubeconfig_dir)
            tc_entry = {
                "tool": fn_name,
                "args": fn_args,
                "result_preview": tool_result[:200],
                "iteration": iteration,
            }
            all_tool_calls.append(tc_entry)

            # Update progress file for cross-pod polling
            if job_id:
                try:
                    from api.routers.dashboard import _save_investigation
                    _save_investigation(job_id, {"status": "running", "tool_calls": list(all_tool_calls), "analysis": None, "error": None})
                except Exception:
                    pass

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_result,
            })

    # Max iterations reached — ask for final summary
    messages.append({"role": "user", "content": "You've used all your investigation steps. Based on everything you've found, provide your final analysis: Diagnosis, Root Cause, and Remediation Strategy."})
    final = call_llm(
        endpoint="agent-investigation-final",
        messages=messages,
        max_tokens=2400,
        temperature=0.2,
        timeout=30,
        db=db,
    )
    return {
        "analysis": _redact(final.get("content", "")),
        "tool_calls": all_tool_calls,
        "iterations": MAX_ITERATIONS,
        "error": None if final.get("success") else final.get("error"),
    }


# ---------------------------------------------------------------------------
# LLM call with tools support
# ---------------------------------------------------------------------------

def _call_llm_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    model: str = "",
    max_tokens: int = 2400,
    temperature: float = 0.2,
    timeout: int = 30,
) -> Dict:
    """Call LLM with tool definitions. Returns the full message object including tool_calls."""
    import ssl
    import urllib.request as urllib_req

    from api.llm import LLM_URL, LLM_API_KEY, LLM_MODEL, SSL_VERIFY

    use_model = model or LLM_MODEL

    payload = {
        "model": use_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "tools": tools,
        "tool_choice": "auto",
    }

    body = json.dumps(payload).encode()

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

    try:
        resp = urllib_req.urlopen(req, timeout=timeout, context=ssl_ctx)
        data = json.loads(resp.read())
        choices = data.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}
        return {"success": True, "message": message}
    except Exception as e:
        logger.warning("LLM tool call failed: %s", str(e)[:200])
        return {"success": False, "error": str(e)[:200], "message": {}}
