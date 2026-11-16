#!/usr/bin/env python3
"""Credential replication check — alert when a known credential gains copies.

Why: `fvmw-password` reached 951 live copies before anyone noticed, and
`aap_image_admin_password` 665. Rotation updates the store; nothing updates or
even counts the copies in AnarchySubject vars and Deployment env.

This compares what is deployed now against a frozen baseline of copy counts and
reports only *increases*. Read-only: it hashes strings in memory and never
stores or prints a value.

Baseline: `data/credential-baseline.json`, generated from a full cross-reference
run (hashes only, no values).

Usage:
  python3 -m scripts.credential_replication_check \
      --cluster ocp-us-east-1 --kubeconfig ~/.kube/control-plane

  # report to StarGate as evaluations (external evidence)
  ... --api-url http://stargate-api:8090 --api-key "$STARGATE_ADMIN_API_KEY"

Exit code is 1 when drift is found, so it can gate a job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

BASELINE_DEFAULT = str(Path(__file__).parent.parent / "data" / "credential-baseline.json")
DEFAULT_TOLERANCE = 5  # ignore small churn; a real replication jumps by much more


def _leaves(prefix: str, value: Any, depth: int = 0) -> Iterable[Tuple[str, str]]:
    if depth > 8:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(f"{prefix}.{key}", item, depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(f"{prefix}[{index}]", item, depth + 1)
    elif isinstance(value, str):
        yield prefix, value


def _oc(kubeconfig: str, args, timeout: int = 300):
    proc = subprocess.run(
        ["oc"] + args + ["-o", "json", f"--request-timeout={timeout}s"],
        capture_output=True, env={**os.environ, "KUBECONFIG": kubeconfig}, timeout=timeout + 60,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def count_live(kubeconfig: str) -> Dict[str, int]:
    """Count live copies per sha256 across AnarchySubject vars and Deployment env."""
    counts: Dict[str, int] = {}

    def bump(text: str) -> None:
        value = text.strip()
        if 8 <= len(value) <= 16384:
            digest = hashlib.sha256(value.encode()).hexdigest()[:16]
            counts[digest] = counts.get(digest, 0) + 1

    subjects = _oc(kubeconfig, ["get", "anarchysubjects", "-A"])
    for item in (subjects or {}).get("items", []):
        for _, value in _leaves("spec.vars", (item.get("spec") or {}).get("vars") or {}):
            bump(value)

    deployments = _oc(kubeconfig, ["get", "deployments", "-A"])
    for item in (deployments or {}).get("items", []):
        spec = ((item.get("spec") or {}).get("template") or {}).get("spec") or {}
        for container in spec.get("containers") or []:
            for env in container.get("env") or []:
                if env.get("value") and not env.get("valueFrom"):
                    bump(env["value"])

    return counts


def diff_counts(baseline: Dict[str, Dict[str, Any]], current: Dict[str, int],
                tolerance: int = DEFAULT_TOLERANCE) -> list:
    """Return credentials whose live copy count rose beyond tolerance."""
    drift = []
    for digest, entry in baseline.items():
        expected = int(entry.get("count", 0))
        now = current.get(digest, 0)
        if now > expected + tolerance:
            drift.append({
                "sha256_16": digest,
                "credential": entry.get("label", ""),
                "baseline_copies": expected,
                "live_copies": now,
                "increase": now - expected,
            })
    drift.sort(key=lambda item: -item["increase"])
    return drift


def report(drift: list, api_url: str, api_key: str, cluster: str) -> int:
    posted = 0
    for item in drift:
        payload = {
            "source": "credential-replication",
            "outcome": "fail",
            "lab_code": "(credential)",
            "cluster_name": f"replication:{item['sha256_16']}",
            "error_summary": (
                f"{item['credential'] or item['sha256_16']} grew from "
                f"{item['baseline_copies']} to {item['live_copies']} live copies "
                f"(+{item['increase']}) on {cluster}"
            ),
        }
        request = urllib.request.Request(
            api_url.rstrip("/") + "/integration/external-evidence",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=15)
            posted += 1
        except Exception as exc:  # noqa: BLE001 — reporting must not abort the check
            print(f"warn: could not report {item['sha256_16']}: {exc}", file=sys.stderr)
    return posted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--baseline", default=BASELINE_DEFAULT)
    parser.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE)
    parser.add_argument("--api-url", default="")
    parser.add_argument("--api-key", default=os.environ.get("STARGATE_ADMIN_API_KEY", ""))
    parser.add_argument("--json", action="store_true", help="print machine-readable output only")
    args = parser.parse_args(argv)

    with open(args.baseline) as handle:
        baseline_all = json.load(handle)
    baseline = (baseline_all.get("clusters") or {}).get(args.cluster, {})

    if not baseline:
        print(f"no baseline for cluster {args.cluster} — nothing to compare", file=sys.stderr)
        return 0

    current = count_live(args.kubeconfig)
    drift = diff_counts(baseline, current, args.tolerance)

    result = {
        "cluster": args.cluster,
        "baseline_credentials": len(baseline),
        "observed_matches": sum(1 for digest in baseline if current.get(digest)),
        "drift": drift,
    }
    print(json.dumps(result, indent=1 if not args.json else None))

    if drift and args.api_url and args.api_key:
        result["reported"] = report(drift, args.api_url, args.api_key, args.cluster)

    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
