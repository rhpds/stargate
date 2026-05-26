"""Run report data structures and formatters for CLI output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class StageReportData:
    stage_id: str
    status: str
    outcome: Optional[str] = None
    failure_class: Optional[str] = None
    message: Optional[str] = None
    duration_seconds: Optional[float] = None
    evidence_count: int = 0


@dataclass
class RunReportData:
    run_id: str
    demo_id: str
    namespace: str
    status: str
    rubric_version: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    stages: List[StageReportData] = field(default_factory=list)


def format_run_report_text(report: RunReportData) -> str:
    passed = sum(1 for s in report.stages if s.outcome == "pass")
    failed = sum(1 for s in report.stages if s.outcome == "fail")
    warned = sum(1 for s in report.stages if s.outcome == "warn")
    total = len(report.stages)

    lines = [
        f"Run Report: {report.run_id}",
        f"  demo: {report.demo_id}",
        f"  namespace: {report.namespace}",
        f"  status: {report.status}",
        f"  rubric_version: {report.rubric_version}",
        f"  stages: {passed} passed, {failed} failed, {warned} warned, {total} total",
        "",
        "Stages:",
    ]

    for s in report.stages:
        icon = _stage_icon(s.outcome or s.status)
        line = f"  [{icon}] {s.stage_id}: {s.outcome or s.status}"
        if s.duration_seconds is not None:
            line += f" ({s.duration_seconds:.1f}s)"
        if s.evidence_count > 0:
            line += f" [{s.evidence_count} evidence]"
        lines.append(line)

        if s.failure_class:
            lines.append(f"      failure_class: {s.failure_class}")
        if s.message and s.outcome not in ("pass", None):
            lines.append(f"      message: {s.message}")

    failed_stages = [s for s in report.stages if s.outcome == "fail"]
    if failed_stages:
        lines.append("")
        lines.append("Failed Stages:")
        for s in failed_stages:
            lines.append(f"  - {s.stage_id}: {s.failure_class or 'unknown'}")
            if s.message:
                lines.append(f"    {s.message}")

    return "\n".join(lines)


def format_run_report_yaml(report: RunReportData) -> str:
    data = {
        "run_id": report.run_id,
        "demo_id": report.demo_id,
        "namespace": report.namespace,
        "status": report.status,
        "rubric_version": report.rubric_version,
        "stages": [],
    }
    for s in report.stages:
        stage_data = {"stage_id": s.stage_id, "status": s.status}
        if s.outcome:
            stage_data["outcome"] = s.outcome
        if s.failure_class:
            stage_data["failure_class"] = s.failure_class
        if s.message:
            stage_data["message"] = s.message
        if s.duration_seconds is not None:
            stage_data["duration_seconds"] = s.duration_seconds
        if s.evidence_count > 0:
            stage_data["evidence_count"] = s.evidence_count
        data["stages"].append(stage_data)

    passed = sum(1 for s in report.stages if s.outcome == "pass")
    failed = sum(1 for s in report.stages if s.outcome == "fail")
    warned = sum(1 for s in report.stages if s.outcome == "warn")
    data["summary"] = {"passed": passed, "failed": failed, "warned": warned, "total": len(report.stages)}

    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def _stage_icon(outcome: str) -> str:
    if outcome in ("pass", "passed"):
        return "+"
    elif outcome in ("warn", "warned"):
        return "~"
    elif outcome in ("fail", "failed"):
        return "X"
    return "-"
