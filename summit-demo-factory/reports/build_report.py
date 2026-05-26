"""Generate build TDD red/green reports from pytest results."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from api.app.models import BuildReport, BuildStageReport, BuildStageResult

BUILD_STAGES = {
    "schema_models": "tests/test_schemas.py",
    "rubric_parser": "tests/test_rubric_loader.py",
    "rubric_evaluator": "tests/test_rubric_evaluator.py",
    "run_api": "tests/test_api.py",
    "evidence_store": "tests/test_db.py",
    "cli": "tests/test_cli.py",
    "report_generator": "tests/test_report_snapshots.py",
    "simulated_e2e": "tests/test_e2e_simulated.py",
    "openshift_dry_run": "tests/test_collectors.py",
    "tekton_integration": "tests/test_tekton.py",
    "ai_boundaries": "tests/test_ai_boundaries.py",
    "json_schema_contracts": "tests/test_json_schema_contracts.py",
    "build_rubrics": "tests/test_build_rubrics.py",
    "demo_definitions": "tests/test_demo_definitions.py",
    "vm_model_lanes": "tests/test_vm_model_lanes.py",
    "build_report": "tests/test_build_report.py",
}


def run_pytest_for_stage(test_path: str, project_root: Path) -> Tuple[int, int, int]:
    full_path = project_root / test_path
    if not full_path.exists():
        return 0, 0, 0

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(full_path), "-v", "--tb=no", "-q"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
        env=env,
    )

    passed = 0
    failed = 0
    for line in result.stdout.splitlines():
        if "passed" in line or "failed" in line:
            parts = line.split()
            for i, part in enumerate(parts):
                word = part.rstrip(",")
                if word == "passed" and i > 0:
                    try:
                        passed = int(parts[i - 1])
                    except ValueError:
                        pass
                if word == "failed" and i > 0:
                    try:
                        failed = int(parts[i - 1])
                    except ValueError:
                        pass

    total = passed + failed
    return total, passed, failed


def generate_build_report(project_root: Optional[Path] = None) -> BuildReport:
    if project_root is None:
        project_root = Path(__file__).parent.parent

    git_sha = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(project_root),
        )
        if result.returncode == 0:
            git_sha = result.stdout.strip()
    except FileNotFoundError:
        pass

    now = datetime.now(timezone.utc)
    build_run_id = f"local-{now.strftime('%Y%m%d-%H%M%S')}"

    stages: List[BuildStageReport] = []
    blocking: List[str] = []

    for stage_name, test_path in BUILD_STAGES.items():
        total, passed, failed = run_pytest_for_stage(test_path, project_root)
        if total == 0:
            result_status = BuildStageResult.RED
        else:
            result_status = BuildStageResult.GREEN if failed == 0 else BuildStageResult.RED

        stages.append(BuildStageReport(
            name=stage_name,
            result=result_status,
            tests=total,
            failures=failed,
        ))

        if result_status == BuildStageResult.RED and total > 0:
            blocking.append(stage_name)

    all_green = all(s.result == BuildStageResult.GREEN for s in stages if s.tests > 0)
    has_tests = any(s.tests > 0 for s in stages)
    overall = BuildStageResult.GREEN if (all_green and has_tests) else BuildStageResult.RED

    return BuildReport(
        build_run_id=build_run_id,
        git_sha=git_sha,
        status=overall,
        stages=stages,
        blocking=blocking,
    )


def format_report_text(report: BuildReport) -> str:
    lines = [
        f"Build Report: {report.build_run_id}",
        f"Git SHA: {report.git_sha or 'unknown'}",
        f"Status: {report.status.value.upper()}",
        "",
        "Stages:",
    ]
    for stage in report.stages:
        icon = "+" if stage.result == BuildStageResult.GREEN else "X"
        lines.append(f"  [{icon}] {stage.name}: {stage.result.value} "
                      f"({stage.tests} tests, {stage.failures} failures)")

    if report.blocking:
        lines.append("")
        lines.append("Blocking:")
        for b in report.blocking:
            lines.append(f"  - {b}")

    return "\n".join(lines)


def format_report_yaml(report: BuildReport) -> str:
    data = json.loads(report.model_dump_json())
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    report = generate_build_report()
    print(format_report_text(report))
    print()
    print("--- YAML ---")
    print(format_report_yaml(report))
