"""Weekly precision digest — a narrative document about the numbers.

Numbers stay behind tools; this turns a week of precision data into something
that can be indexed and cited by `ask`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List


CAVEAT = (
    "`self-resolved` counts labs that also passed the same stage in the window. "
    "It bounds noise from above — a lab can genuinely fail, be remediated, and "
    "pass later — so this is a noise signal, not ground truth."
)


def _index(report: Dict) -> Dict[str, Dict]:
    return {row["failure_class"]: row for row in report.get("classes", [])}


def build_digest(current: Dict, previous: Dict, generated_at: datetime) -> str:
    """Markdown for one week, with the previous week for comparison."""
    now_rows = _index(current)
    before_rows = _index(previous)

    lines: List[str] = [
        f"# Failure precision — week of {generated_at:%Y-%m-%d}",
        "",
        f"Generated {generated_at:%Y-%m-%dT%H:%MZ} from {current['summary']['evaluations']} "
        f"failure evaluations across {current['summary']['classes']} classes.",
        "",
        "| Class | Evals | Labs | Self-resolved | vs prev week |",
        "|---|---|---|---|---|",
    ]

    for failure_class, row in sorted(
        now_rows.items(), key=lambda item: -item[1]["evaluations"]
    )[:15]:
        before = before_rows.get(failure_class)
        delta = row["evaluations"] - (before["evaluations"] if before else 0)
        lines.append(
            f"| `{failure_class}` | {row['evaluations']} | {row['labs']} | "
            f"{row['self_resolved_pct']}% | {delta:+d} |"
        )

    gone = [name for name in before_rows if name not in now_rows]
    appeared = [name for name in now_rows if name not in before_rows]

    lines += ["", "## What changed", ""]
    movements = []
    for name, row in now_rows.items():
        before = before_rows.get(name)
        if not before:
            continue
        change = row["self_resolved_pct"] - before["self_resolved_pct"]
        if abs(change) >= 10:
            movements.append(
                f"- `{name}` self-resolution {before['self_resolved_pct']}% → "
                f"{row['self_resolved_pct']}%"
            )
    lines += movements or ["- No class moved its self-resolution by 10 points or more."]
    if appeared:
        lines.append(f"- New this week: {', '.join(f'`{n}`' for n in appeared[:8])}")
    if gone:
        lines.append(f"- Silent this week: {', '.join(f'`{n}`' for n in gone[:8])}")

    lines += ["", "## Reading it", "", CAVEAT, ""]
    return "\n".join(lines)


