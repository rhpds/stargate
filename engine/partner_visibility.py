"""Partner catalog visibility — make the invisible channel visible.

From Billy's 90-day analysis (Confluence 511804406): partner items fail at
16.8% overall (60% higher than internal PROD), several in the 50-90% range,
and 'nobody's been watching them' — the standard biweekly report doesn't
break out the partner channel.

The channel distinction lives in the reporting DB Billy queried; StarGate's
evaluations don't carry the ordering user's identity, so the channel is
encoded as a maintained registry (config/partner-catalog.yaml) of
partner-channel items with Billy's 90-day baselines for comparison.

Matching is normalized (case + separators) against lab_codes, ci_names,
and agnosticv_paths from lab_mappings, using each item's match_hints.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import yaml
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.partner_visibility")

_REGISTRY_CACHE: Optional[List[Dict]] = None


def _normalize(s: str) -> str:
    return re.sub(r"[-_./\s]+", "", (s or "").lower())


def load_partner_registry() -> List[Dict]:
    """Partner items from config/partner-catalog.yaml (cached)."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    path = Path(__file__).parent.parent / "config" / "partner-catalog.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        _REGISTRY_CACHE = (data or {}).get("items", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("partner registry load failed: %s", e)
        _REGISTRY_CACHE = []
    return _REGISTRY_CACHE


def _match_lab(lab_code: str, ci_name: Optional[str], agnosticv_path: Optional[str],
               hints: List[str]) -> bool:
    haystacks = " ".join(filter(None, [lab_code, ci_name, agnosticv_path]))
    norm_hay = _normalize(haystacks)
    return any(_normalize(h) in norm_hay for h in hints)


def partner_visibility(db: Session, days: int = 7) -> Dict:
    """Failure-rate breakdown for registered partner items vs the fleet.

    Returns per-item current rates (from evaluations), Billy's 90-day
    baselines, matched lab_codes, and the fleet comparison — the partner
    breakdown the biweekly report lacks.
    """
    registry = load_partner_registry()
    if not registry:
        return {"error": "partner registry empty or missing", "items": []}

    # lab identity rows for matching
    rows = db.execute(text(
        "SELECT lab_code, ci_name, agnosticv_path FROM lab_mappings"
    )).fetchall()
    identities = [
        {"lab_code": r[0], "ci_name": r[1], "agnosticv_path": r[2]} for r in rows
    ]

    # per-item matched lab codes
    item_matches: List[Dict] = []
    matched_labs: set = set()
    for item in registry:
        hints = item.get("match_hints") or []
        labs = sorted({
            i["lab_code"] for i in identities
            if _match_lab(i["lab_code"], i["ci_name"], i["agnosticv_path"], hints)
        })
        matched_labs.update(labs)
        item_matches.append({**item, "matched_lab_codes": labs, "matched": bool(labs)})

    # evaluation stats for matched labs (one query); cutoff computed in
    # Python for portability (SQLite tests, Postgres production)
    stats: Dict[str, Dict[str, int]] = {}
    since = datetime.now(timezone.utc) - timedelta(days=days)
    if matched_labs:
        names = sorted(matched_labs)
        rows = db.execute(text(
            "SELECT lab_code,"
            " count(*) FILTER (WHERE outcome='fail') AS fails,"
            " count(*) AS total"
            " FROM evaluations"
            " WHERE evaluated_at > :since"
            " AND lab_code IN :labs"
            " GROUP BY lab_code"
        ).bindparams(bindparam("labs", expanding=True)),
            {"since": since, "labs": names}).fetchall()
        stats = {r[0]: {"fails": r[1], "total": r[2]} for r in rows}

    items_out: List[Dict] = []
    partner_fails = partner_total = 0
    for item in item_matches:
        entry: Dict = {
            "name": item["name"],
            "baseline_failure_rate": item.get("baseline_failure_rate"),
            "baseline_note": item.get("baseline_note"),
            "matched": item["matched"],
            "matched_lab_codes": item["matched_lab_codes"][:5],
        }
        if item["matched"]:
            f = sum(stats.get(lab, {}).get("fails", 0) for lab in item["matched_lab_codes"])
            t = sum(stats.get(lab, {}).get("total", 0) for lab in item["matched_lab_codes"])
            partner_fails += f
            partner_total += t
            entry["evaluations"] = t
            entry["failures"] = f
            entry["failure_rate"] = round(100.0 * f / t, 1) if t else None
            entry["delta_vs_baseline"] = (
                round(entry["failure_rate"] - item["baseline_failure_rate"], 1)
                if entry["failure_rate"] is not None and item.get("baseline_failure_rate")
                else None
            )
        else:
            entry["evaluations"] = 0
            entry["failure_rate"] = None
            entry["note"] = "no matching lab_codes — check match_hints or registry"
        items_out.append(entry)

    items_out.sort(key=lambda e: (e.get("failure_rate") is None,
                                  -(e.get("failure_rate") or 0)))

    # fleet comparison over the same window
    fleet = db.execute(text(
        "SELECT count(*) FILTER (WHERE outcome='fail'), count(*)"
        " FROM evaluations WHERE evaluated_at > :since"
    ), {"since": since}).fetchone()

    return {
        "window_days": days,
        "partner_items_registered": len(registry),
        "partner_items_matched": sum(1 for i in items_out if i["matched"]),
        "partner_failure_rate": (
            round(100.0 * partner_fails / partner_total, 1) if partner_total else None
        ),
        "partner_evaluations": partner_total,
        "partner_failures": partner_fails,
        "fleet_failure_rate": (
            round(100.0 * fleet[0] / fleet[1], 1) if fleet[1] else None
        ),
        "fleet_evaluations": fleet[1],
        "items": items_out,
        "note": (
            "Baselines are the documented 90-day analysis (Jul 28 - Oct 28 2026, "
            "Confluence 511804406). 'delta_vs_baseline' > 0 means worse than the "
            "documented snapshot. Fleet rate includes all environments — compare "
            "trends, not absolute levels."
        ),
    }
