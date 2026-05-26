"""Summit Demo Factory CLI — local and API-connected commands."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from api.app.models import Rubric, Run, RunStatus, StageOutcome
from api.app.rubric_evaluator import EvaluationResult, evaluate_rubric
from api.app.rubric_loader import load_rubric, load_rubrics_from_directory, RubricLoadError
from cli.run_report import format_run_report_text, format_run_report_yaml, RunReportData, StageReportData
from reports.build_report import format_report_text, generate_build_report


RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sdf",
        description="Summit Demo Factory — control plane CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # validate-rubric
    p_vr = sub.add_parser("validate-rubric", help="Validate a rubric YAML file")
    p_vr.add_argument("path", help="Path to rubric YAML file or directory")

    # create-run
    p_cr = sub.add_parser("create-run", help="Create a run from a demo definition")
    p_cr.add_argument("definition", help="Path to demo definition YAML")
    p_cr.add_argument("--run-id", help="Override run ID")
    p_cr.add_argument("--namespace", help="Override namespace")

    # start-stage
    p_ss = sub.add_parser("start-stage", help="Start a stage")
    p_ss.add_argument("run_id")
    p_ss.add_argument("stage_id")

    # submit-evidence
    p_se = sub.add_parser("submit-evidence", help="Submit evidence for a stage")
    p_se.add_argument("run_id")
    p_se.add_argument("stage_id")
    p_se.add_argument("evidence_file", help="Path to evidence JSON file")

    # evaluate-stage
    p_es = sub.add_parser("evaluate-stage", help="Evaluate a stage against its rubric")
    p_es.add_argument("run_id")
    p_es.add_argument("stage_id")

    # report
    p_rp = sub.add_parser("report", help="Generate a run report")
    p_rp.add_argument("run_id")
    p_rp.add_argument("--format", choices=["text", "yaml", "json"], default="text")

    # run-fixture
    p_rf = sub.add_parser("run-fixture", help="Run a complete fixture through all stages")
    p_rf.add_argument("fixture", help="Path to fixture YAML")
    p_rf.add_argument("--format", choices=["text", "yaml", "json"], default="text")

    # build-report
    sub.add_parser("build-report", help="Generate build TDD red/green report")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "validate-rubric":
            return cmd_validate_rubric(args)
        elif args.command == "create-run":
            return cmd_create_run(args)
        elif args.command == "run-fixture":
            return cmd_run_fixture(args)
        elif args.command == "build-report":
            return cmd_build_report(args)
        elif args.command == "evaluate-stage":
            return cmd_evaluate_stage(args)
        elif args.command == "report":
            return cmd_report(args)
        else:
            print(f"Command '{args.command}' requires a running API (Phase 2+).")
            print("Use 'run-fixture' for local-only workflow.")
            return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# --- Local state for CLI-only mode ---

_local_runs: Dict[str, dict] = {}
_local_stages: Dict[str, Dict[str, dict]] = {}
_local_evidence: Dict[str, Dict[str, List[dict]]] = {}


def cmd_validate_rubric(args) -> int:
    path = Path(args.path)
    try:
        if path.is_dir():
            rubrics = load_rubrics_from_directory(path)
            for r in rubrics:
                print(f"  {r.id} ({r.version}) — {len(r.exit_criteria)} exit criteria")
            print(f"Validated {len(rubrics)} rubrics.")
        else:
            rubric = load_rubric(path)
            print(f"  {rubric.id} ({rubric.version}) — {len(rubric.exit_criteria)} exit criteria")
        return 0
    except RubricLoadError as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1


def cmd_create_run(args) -> int:
    path = Path(args.definition)
    if not path.exists():
        print(f"Definition not found: {path}", file=sys.stderr)
        return 1

    data = yaml.safe_load(path.read_text())
    demo_id = data.get("demo_id", "unknown")
    ns_prefix = data.get("namespace_prefix", "demo")
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    run_id = args.run_id or f"{demo_id}-{now_str}"
    namespace = args.namespace or f"{ns_prefix}-{now_str[:8]}"

    run_data = {
        "run_id": run_id,
        "demo_id": demo_id,
        "namespace": namespace,
        "requested_by": "cli-user",
        "status": "pending",
        "rubric_version": data.get("rubric_version", "v0.1.0"),
        "stages": [s["stage_id"] for s in data.get("stages", [])],
    }

    _local_runs[run_id] = run_data
    _local_stages[run_id] = {}
    _local_evidence[run_id] = {}

    print(f"Run created: {run_id}")
    print(f"  demo: {demo_id}")
    print(f"  namespace: {namespace}")
    print(f"  stages: {', '.join(run_data['stages'])}")
    return 0


def cmd_evaluate_stage(args) -> int:
    run_id = args.run_id
    stage_id = args.stage_id

    rubric = _load_rubric(stage_id)
    if not rubric:
        print(f"No rubric found for stage: {stage_id}", file=sys.stderr)
        return 1

    evidence_data = {}
    if run_id in _local_evidence and stage_id in _local_evidence[run_id]:
        for ev in _local_evidence[run_id][stage_id]:
            evidence_data.update(ev.get("observed", {}))

    result = evaluate_rubric(rubric, evidence_data)
    _print_evaluation(result)
    return 0 if result.outcome != StageOutcome.FAIL else 1


def cmd_report(args) -> int:
    run_id = args.run_id
    if run_id not in _local_runs:
        print(f"Run not found: {run_id}", file=sys.stderr)
        return 1

    report = _build_run_report(run_id)
    if args.format == "yaml":
        print(format_run_report_yaml(report))
    elif args.format == "json":
        print(json.dumps(report.__dict__, default=str, indent=2))
    else:
        print(format_run_report_text(report))
    return 0


def cmd_run_fixture(args) -> int:
    path = Path(args.fixture)
    if not path.exists():
        print(f"Fixture not found: {path}", file=sys.stderr)
        return 1

    fixture = yaml.safe_load(path.read_text())
    if not isinstance(fixture, dict) or "run" not in fixture:
        print("Fixture YAML must have a 'run' key", file=sys.stderr)
        return 1
    run_info = fixture["run"]
    if "run_id" not in run_info:
        print("Fixture must have 'run.run_id'", file=sys.stderr)
        return 1
    run_id = run_info["run_id"]

    rubrics = _load_all_rubrics()

    demo_id = run_info.get("demo_id", "")
    demo_def_path = Path(__file__).parent.parent / "demo-definitions" / f"{demo_id}.yaml"
    if demo_def_path.exists():
        demo_def = yaml.safe_load(demo_def_path.read_text())
        expected_order = [s["stage_id"] for s in demo_def.get("stages", [])]
        actual_order = [s["stage_id"] for s in fixture.get("stages", [])]
        if actual_order != expected_order:
            print(f"  Warning: fixture stages {actual_order} do not match "
                  f"demo definition order {expected_order}")

    print(f"=== Fixture Run: {run_id} ===")
    print(f"  demo: {demo_id}")
    print(f"  namespace: {run_info['namespace']}")
    print()

    stage_reports: List[StageReportData] = []
    all_passed = True
    has_failure = False

    for stage_data in fixture.get("stages", []):
        stage_id = stage_data["stage_id"]
        evidence = stage_data.get("evidence", {})
        expected = stage_data.get("expected_outcome")

        rubric = rubrics.get(stage_id)
        if not rubric:
            print(f"  [{stage_id}] SKIP — no rubric found")
            stage_reports.append(StageReportData(
                stage_id=stage_id, status="skipped", outcome=None,
            ))
            continue

        result = evaluate_rubric(rubric, evidence)
        icon = _outcome_icon(result.outcome)
        match_str = ""
        if expected:
            matched = result.outcome.value == expected
            match_str = " (expected)" if matched else f" (MISMATCH: expected {expected})"
            if not matched:
                all_passed = False

        if result.outcome == StageOutcome.FAIL:
            has_failure = True

        print(f"  [{icon}] {stage_id}: {result.outcome.value}{match_str}")
        if result.failure_class:
            print(f"      failure_class: {result.failure_class}")
        if result.message and result.outcome != StageOutcome.PASS:
            print(f"      message: {result.message}")

        stage_reports.append(StageReportData(
            stage_id=stage_id,
            status=result.outcome.value,
            outcome=result.outcome.value,
            failure_class=result.failure_class,
            message=result.message,
            evidence_count=len(evidence),
        ))

    print()

    report = RunReportData(
        run_id=run_id,
        demo_id=run_info["demo_id"],
        namespace=run_info["namespace"],
        status="completed" if not has_failure else "failed",
        rubric_version=run_info.get("rubric_version", "unknown"),
        stages=stage_reports,
    )

    if args.format == "yaml":
        print(format_run_report_yaml(report))
    elif args.format == "json":
        print(json.dumps(report.__dict__, default=str, indent=2))
    else:
        print(format_run_report_text(report))

    return 0 if all_passed else 1


def cmd_build_report(args) -> int:
    project_root = Path(__file__).parent.parent
    report = generate_build_report(project_root)
    print(format_report_text(report))
    return 0 if report.status.value == "green" else 1


# --- Helpers ---

def _load_rubric(stage_id: str) -> Optional[Rubric]:
    rubrics = _load_all_rubrics()
    return rubrics.get(stage_id)


def _load_all_rubrics() -> Dict[str, Rubric]:
    rubrics = {}
    if RUBRIC_DIR.is_dir():
        try:
            for r in load_rubrics_from_directory(RUBRIC_DIR):
                rubrics[r.stage] = r
        except RubricLoadError:
            pass
    return rubrics


def _print_evaluation(result: EvaluationResult):
    icon = _outcome_icon(result.outcome)
    print(f"[{icon}] {result.stage_id}: {result.outcome.value}")
    if result.failure_class:
        print(f"  failure_class: {result.failure_class}")
    if result.message:
        print(f"  message: {result.message}")
    for c in result.criteria_results:
        ci = "+" if c.passed else "X"
        req = "required" if c.required else "optional"
        print(f"  [{ci}] {c.name} ({req})")


def _outcome_icon(outcome: StageOutcome) -> str:
    if outcome == StageOutcome.PASS:
        return "+"
    elif outcome == StageOutcome.WARN:
        return "~"
    else:
        return "X"


def _build_run_report(run_id: str) -> RunReportData:
    run = _local_runs[run_id]
    stages_data = _local_stages.get(run_id, {})
    return RunReportData(
        run_id=run_id,
        demo_id=run["demo_id"],
        namespace=run["namespace"],
        status=run["status"],
        rubric_version=run.get("rubric_version", "unknown"),
        stages=[
            StageReportData(stage_id=sid, status=sd.get("status", "pending"))
            for sid, sd in stages_data.items()
        ],
    )


if __name__ == "__main__":
    sys.exit(main())
