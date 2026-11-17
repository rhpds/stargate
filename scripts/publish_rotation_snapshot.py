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
import csv
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from collectors.rotation_sync import bucket_for

DEFAULT_API_URL = "http://stargate-api.stargate.svc:8090"
COUNTERS = ("verified_live", "live_locations", "untracked_live")

logger = logging.getLogger("stargate.rotation_publish")


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
    seen: Dict[str, List[tuple]] = {}
    for row in snapshot.get("by_provider") or []:
        counts = {key: int(row.get(key) or 0) for key in COUNTERS}
        if not any(counts.values()):
            continue
        provider = bucket_for(row.get("provider") or "")
        triple = tuple(counts[key] for key in COUNTERS)
        # Two raw names can be two views of one audit bucket ('Storage' and
        # 'Datastores' both mapped to 'Datastores / storage'). Identical
        # evidence is the same credentials counted twice, not two sets — count
        # it once rather than inflate the fleet.
        if triple in seen.setdefault(provider, []):
            logger.warning(
                "Skipping duplicate evidence for %s from %r: %s",
                provider, row.get("provider"), triple,
            )
            continue
        seen[provider].append(triple)
        entry = buckets.setdefault(provider, {key: 0 for key in COUNTERS})
        for key in COUNTERS:
            entry[key] += counts[key]

    providers: List[Dict[str, Any]] = [
        {"provider": provider, **counts}
        for provider, counts in sorted(buckets.items())
    ]
    return {"date": snapshot["date"], "providers": providers}


def build_credentials(csv_path: str) -> List[Dict[str, Any]]:
    """Read the audit's coverage export into per-credential rows.

    Accepts either export: `jira-coverage.csv` (sha256_16, jira) or
    `credential-classification.csv` (credential_id, provider, example_location).
    """
    credentials: List[Dict[str, Any]] = []
    with open(csv_path, newline="") as handle:
        for row in csv.DictReader(handle):
            credential_id = (row.get("sha256_16") or row.get("credential_id") or "").strip()
            if not credential_id:
                continue
            try:
                copies = int(row.get("live_copies") or 0)
            except ValueError:
                copies = 0
            credentials.append({
                "id": credential_id,
                "credential": (row.get("credential") or "")[:200],
                "provider": (row.get("provider") or "")[:80],
                "live_copies": copies,
                "clusters": (row.get("clusters") or "")[:500],
                "example_location": (row.get("example_location") or "")[:300],
                "coverage": (row.get("coverage") or "")[:30],
                "jira_keys": (row.get("jira") or "")[:200],
            })
    return credentials


def publish(payload: Dict[str, Any], api_url: str, api_key: str) -> Dict[str, Any]:
    return _post("/integration/rotation-snapshot", payload, api_url, api_key)


def publish_credentials(payload: Dict[str, Any], api_url: str, api_key: str) -> Dict[str, Any]:
    return _post("/integration/rotation-credentials", payload, api_url, api_key)


def _post(path: str, payload: Dict[str, Any], api_url: str, api_key: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
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
    parser.add_argument(
        "--credentials-csv",
        help="jira-coverage.csv or credential-classification.csv (per-credential rows)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    snapshot = load_snapshot(args.snapshot)
    payload = build_payload(snapshot)
    credentials = (
        {"date": snapshot["date"], "credentials": build_credentials(args.credentials_csv)}
        if args.credentials_csv
        else None
    )

    if args.dry_run:
        print(json.dumps({"snapshot": payload, "credentials": credentials}, indent=1))
        return 0

    if not args.api_key:
        print("STARGATE_ADMIN_API_KEY (or --api-key) is required", file=sys.stderr)
        return 2

    result = publish(payload, args.api_url, args.api_key)
    print(
        f"published {result.get('providers', 0)} providers for "
        f"{result.get('date')} to {args.api_url}"
    )
    if credentials is not None:
        cred_result = publish_credentials(credentials, args.api_url, args.api_key)
        print(
            f"published {cred_result.get('credentials', 0)} credentials for "
            f"{cred_result.get('date')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
