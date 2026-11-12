#!/usr/bin/env python
"""Cascade Phase 0 backtest — run the replay corpus through Cascade's nano
pipeline offline and audit the decisions against known outcomes.

Implements docs/cascade-shadow-validation-plan.md Phase 0:
  - suppression safety on the documented-incident hold-out set (HARD GATE:
    zero suppressions, at least one survivor per incident)
  - suppression rate on self-resolved patterns (ground truth from
    resolution_records; higher is better, Wilson-intervaled)
  - classification agreement vs the StarGate taxonomy
  - overall compression rate

Stdlib-only, Python 3.9+ (runs under the Cascade proof venv). No StarGate
imports, no network, no production writes. The corpus/resolutions JSONL are
extracted read-only from production; severity_map.json comes from the
StarGate failure-classes taxonomy.

Usage (with the CASCADE repo's venv):
  python scripts/cascade_backtest.py \
    --corpus corpus.jsonl --resolutions resolutions.jsonl \
    --severity-map severity_map.json --cascade-repo /path/to/cascade-compression \
    --out report.json
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone


def wilson(k, n, z=1.96):
    """Wilson 95% interval for k successes in n trials."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(p, 4), round((c - h) / d, 4), round((c + h) / d, 4))


SEVERITY_MAP = {"critical": "critical", "high": "high", "medium": "medium",
                "warning": "medium", "low": "low", "info": "info"}

# Documented-incident hold-out windows (docs/incident-validation-2026-10.md).
# A suppression here is a finding, not a statistic.
INCIDENT_WINDOWS = [
    ("sso_5xx_json_decode", "2026-10-21", "2026-10-23"),
    ("cnv_account_bloat", "2026-09-28", "2026-10-15"),
    ("ocpv_saturation", "2026-10-13", "2026-10-15"),
    ("event_pool_exhaustion", "2026-09-01", "2026-11-01"),
]
SATURATION_CLASSES = {"vmi_not_running", "datavolume_failed",
                      "datavolume_not_ready", "pods_not_ready"}


def parse_ts(value):
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace(" ", "T"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def load_jsonl(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def label_incident(row, ts):
    """Return the incident-window label for a corpus row, or None."""
    fc = (row.get("fc") or "").lower()
    err = (row.get("err") or "")
    item = (row.get("item") or "").lower()
    cluster = (row.get("cluster") or "").lower()
    instance = (row.get("instance") or "").lower()
    for name, start, end in INCIDENT_WINDOWS:
        s = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        e = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
        if not (s <= ts < e):
            continue
        if name == "sso_5xx_json_decode":
            if fc == "json_decode_error" or "Expecting value" in err:
                return name
        elif name == "cnv_account_bloat":
            if "cnv" in item:
                return name
        elif name == "ocpv_saturation":
            if cluster in ("ocpv06", "ocpv08") and fc in SATURATION_CLASSES:
                return name
        elif name == "event_pool_exhaustion":
            if instance.startswith("event"):
                return name
    return None


def build_resolution_index(resolutions):
    """guid -> [(detected, resolved, rtype)] windows.

    Resolution records live in the evaluation universe (lab_code like
    sandbox-{guid}-{catalog}); the corpus lives in the AAP universe (guid +
    catalog_item). The guid segment is the shared key — the failure-class
    vocabularies differ between the two systems and cannot be joined.
    """
    import re
    idx = {}
    for rr in resolutions:
        lab = rr.get("lab") or ""
        m = re.match(r"^[a-z]+-([a-z0-9]{4,7})-", lab)
        if not m:
            continue
        detected = parse_ts(rr.get("detected"))
        resolved = parse_ts(rr.get("resolved")) or detected
        if detected is None:
            continue
        idx.setdefault(m.group(1), []).append((detected, resolved, rr.get("rtype")))
    return idx


def label_resolution(row, ts, index):
    """Resolution bucket for a corpus row via guid + time-window match."""
    guid = (row.get("guid") or "").lower()
    for detected, resolved, rtype in index.get(guid, ()):
        if detected <= ts <= (resolved or detected):
            return rtype or "unknown"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--resolutions", required=True)
    ap.add_argument("--severity-map", required=True)
    ap.add_argument("--cascade-repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch-days", type=int, default=7,
                    help="signals are processed in time-window batches; the "
                         "pipeline's per-decision lookup is quadratic, and "
                         "windowed batches match how collectors actually feed it")
    args = ap.parse_args()

    sys.path.insert(0, args.cascade_repo)
    from cascade_compression.cascade.agents import default_agents
    from cascade_compression.cascade.pipeline import CascadePipeline
    from cascade_compression.cascade.protocol import Signal, Outcome

    corpus = load_jsonl(args.corpus)
    resolutions = load_jsonl(args.resolutions)
    severity_map = json.load(open(args.severity_map))
    res_index = build_resolution_index(resolutions)

    signals, meta = [], {}
    buckets = {}
    skipped = 0
    for row in corpus:
        ts = parse_ts(row.get("ts"))
        if ts is None:
            skipped += 1
            continue
        fc = row.get("fc") or ""
        sev = SEVERITY_MAP.get((severity_map.get(fc) or "medium").lower(), "medium")
        sig = Signal(
            signal_type=fc or "unclassified",
            severity=sev,
            source="stargate/aap/%s" % (row.get("instance") or "unknown"),
            content={
                "task": row.get("task"), "play": row.get("play"),
                "role": row.get("role"), "error": row.get("err"),
                "timestamp": row.get("ts"),
            },
            labels={"cluster": row.get("cluster") or "", "guid": row.get("guid") or "",
                    "catalog_item": row.get("item") or ""},
            namespace=row.get("guid") or row.get("item") or "",
            cluster=row.get("cluster") or "",
        )
        signals.append(sig)
        incident = label_incident(row, ts)
        resolution = label_resolution(row, ts, res_index)
        bucket = incident or ("res:%s" % resolution if resolution else "unmatched")
        meta[str(sig.signal_id)] = {"bucket": bucket, "fc": fc}
        buckets.setdefault(bucket, 0)
        buckets[bucket] += 1

    print("corpus: %d signals (%d skipped, no timestamp)" % (len(signals), skipped))
    print("buckets: " + ", ".join("%s=%d" % kv for kv in sorted(buckets.items())))

    pipeline = CascadePipeline(agents=default_agents())

    # Time-windowed batches (the pipeline's per-decision signal lookup is
    # quadratic in batch size; weekly windows bound it and mirror how the
    # live collectors deliver signals in batches).
    ordered = sorted(range(len(signals)),
                     key=lambda i: signals[i].content.get("timestamp") or "")
    batch_seconds = args.batch_days * 86400
    batches, current, current_start = [], [], None
    for i in ordered:
        sig = signals[i]
        ts = parse_ts(sig.content.get("timestamp"))
        if current_start is None:
            current_start = ts
        if ts and current_start and (ts - current_start).total_seconds() > batch_seconds:
            batches.append(current)
            current, current_start = [], ts
        current.append(sig)
    if current:
        batches.append(current)

    removed = {}
    classified = []
    totals = {"total": 0, "remaining": 0, "suppressed": 0, "deduped": 0,
              "classified": 0, "dropped": 0}
    for bi, batch in enumerate(batches):
        result = pipeline.run(batch)
        totals["total"] += result.total_signals
        totals["remaining"] += len(result.remaining)
        totals["suppressed"] += result.suppressed_count
        totals["deduped"] += result.deduped_count
        totals["classified"] += result.classified_count
        totals["dropped"] += result.dropped_count
        remaining_ids = {str(s.signal_id) for s in result.remaining}
        for d in result.decisions:
            if d.outcome in (Outcome.SUPPRESS, Outcome.DROP, Outcome.DEDUPE):
                removed[str(d.signal_id)] = d.outcome.value
            elif d.outcome == Outcome.CLASSIFY and d.classification:
                classified.append(d)
        for sid in remaining_ids:
            meta[sid]["_rem"] = True
        if (bi + 1) % 10 == 0:
            print("  batch %d/%d: %d signals, %d suppressed so far" % (
                bi + 1, len(batches), totals["total"], totals["suppressed"]))

    stats = {}
    for sid, m in meta.items():
        b = stats.setdefault(m["bucket"], {"total": 0, "suppress": 0, "drop": 0,
                                           "dedupe": 0, "remaining": 0})
        b["total"] += 1
        out = removed.get(sid)
        if out:
            b[out] += 1
        elif m.get("_rem"):
            b["remaining"] += 1

    # Classification agreement (classify decisions with a label, vs taxonomy)
    agree = disagree = unclassified_labeled = 0
    for d in classified:
        fc = meta.get(str(d.signal_id), {}).get("fc", "")
        if not fc:
            unclassified_labeled += 1
        elif d.classification == fc:
            agree += 1
        else:
            disagree += 1

    hard_gate = []
    for name, _, _ in INCIDENT_WINDOWS:
        b = stats.get(name)
        if not b:
            hard_gate.append({"incident": name, "status": "NO SIGNALS MATCHED — "
                             "check window/signature labeling"})
            continue
        removed_n = b["suppress"] + b["drop"]
        ok = removed_n == 0 and b["remaining"] >= 1
        hard_gate.append({
            "incident": name, "signals": b["total"],
            "suppressed": b["suppress"], "dropped": b["drop"],
            "deduped": b["dedupe"], "survivors": b["remaining"],
            "status": "PASS" if ok else "VIOLATION",
        })

    self_res = stats.get("res:self_resolved", {"total": 0, "suppress": 0, "drop": 0})
    self_sup = self_res["suppress"] + self_res["drop"]
    rate, lo, hi = wilson(self_sup, self_res["total"])

    report = {
        "phase": "cascade-backtest-0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {"signals": len(signals), "skipped_no_ts": skipped,
                   "buckets": buckets},
        "compression": {
            "total": totals["total"], "remaining": totals["remaining"],
            "suppressed": totals["suppressed"], "deduped": totals["deduped"],
            "classified": totals["classified"], "dropped": totals["dropped"],
            "ratio": round(1 - totals["remaining"] / max(totals["total"], 1), 4),
            "batch_days": args.batch_days, "batches": len(batches),
        },
        "hard_gate_incidents": hard_gate,
        "self_resolved_suppression": {
            "signals": self_res["total"], "suppressed": self_sup,
            "rate": rate, "wilson_95": [lo, hi],
        },
        "classification_agreement": {
            "agree": agree, "disagree": disagree,
            "unclassified_labeled_by_cascade": unclassified_labeled,
            "rate": round(agree / (agree + disagree), 4) if (agree + disagree) else None,
        },
        "bucket_stats": stats,
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)

    print("\n=== compression ===")
    print("total=%d remaining=%d suppressed=%d deduped=%d dropped=%d ratio=%.3f" % (
        totals["total"], totals["remaining"], totals["suppressed"],
        totals["deduped"], totals["dropped"],
        1 - totals["remaining"] / max(totals["total"], 1)))
    print("\n=== hard gate (documented incidents) ===")
    for g in hard_gate:
        print("%-24s %s (signals=%s suppressed=%s dropped=%s survivors=%s)" % (
            g["incident"], g["status"], g.get("signals"), g.get("suppressed"),
            g.get("dropped"), g.get("survivors")))
    print("\n=== self-resolved suppression ===")
    print("%d/%d = %.1f%% [%.1f, %.1f]" % (self_sup, self_res["total"],
                                           100 * rate, 100 * lo, 100 * hi))
    print("\nreport: %s" % args.out)


if __name__ == "__main__":
    main()
