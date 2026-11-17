#!/usr/bin/env python3
"""Publish a Turkey Vulture audit snapshot to StarGate.

The audit reads Secrets across the fleet under a time-boxed grant and writes
`snapshots/turkeyvulture-YYYY-MM-DD.json` — counts and hashes only, never
values. This posts the verified-live counts to the rotation page:

    python3 -m scripts.publish_rotation_snapshot \
        --snapshot snapshots/turkeyvulture-2026-11-17.json

Why a separate step: StarGate's own SA is `cluster-reader` and cannot read
Secrets, so verification stays an external, read-only audit. The page consumes
the evidence; it must not be able to produce it.

Idempotent: the endpoint upserts per (date, provider), so re-running after a
failed post is safe and the audit can simply call this last.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from collectors.rotation_sync import bucket_for

DEFAULT_API_URL = "http://stargate-api.stargate.svc:8090"
COUNTERS = ("verified_live", "live_locations", "untracked_live")


def load_snapshot(path: str) -> Dict[str, Any]:
    snapshot = json.loads(Path(path).read_text())
    if not isinstance(snapshot, dict) or "by_provider" not in snapshot:
        raise ValueError(f"{path} is not an audit snapshot (no 'by_provider')")
    if not snapshot.get("date"):
        raise ValueError(f"{path} has no 'date'")
    return snapshot


def build_payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse raw provider names into the buckets the rotation page uses.

    The audit's own names can be long tails ('P1 — AWS; DNS/Route 53…') or
    aliases of a ticket bucket. Mapping here means a snapshot provider and a
    Jira provider become the same row. Rows with no evidence are dropped —
    an ingest must never create an empty provider on the page.
    """
    buckets: Dict[str, Dict[str, int]] = {}
    for row in snapshot.get("by_provider") or []:
        counts = {key: int(row.get(key) or 0) for key in COUNTERS}
        if not any(counts.values()):
            continue
        provider = bucket_for(row.get("provider") or "")
        entry = buckets.setdefault(provider, {key: 0 for key in COUNTERS})
        for key in COUNTERS:
            entry[key] += counts[key]

    providers: List[Dict[str, Any]] = [
        {"provider": provider, **counts}
        for provider, counts in sorted(buckets.items())
    ]
    return {"date": snapshot["date"], "providers": providers}


def publish(payload: Dict[str, Any], api_url: str, api_key: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/integration/rotation-snapshot",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"ingest failed: {exc.code} {body}") from exc


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="audit snapshot JSON")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("STARGATE_API_URL", DEFAULT_API_URL),
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("STARGATE_ADMIN_API_KEY", ""),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    snapshot = load_snapshot(args.snapshot)
    payload = build_payload(snapshot)

    if args.dry_run:
        print(json.dumps(payload, indent=1))
        return 0

    if not args.api_key:
        print("STARGATE_ADMIN_API_KEY (or --api-key) is required", file=sys.stderr)
        return 2

    result = publish(payload, args.api_url, args.api_key)
    print(
        f"published {result.get('providers', 0)} providers for "
        f"{result.get('date')} to {args.api_url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
