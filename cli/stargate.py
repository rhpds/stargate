"""StarGate CLI — collect evidence, evaluate rubrics, report results."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from engine.models import Rubric, StageOutcome
from engine.rubric_evaluator import EvaluationResult, evaluate_rubric
from engine.rubric_loader import load_rubric, load_rubrics_from_directory, RubricLoadError
from collectors.openshift.collect_resource_state import (
    CollectedEvidence,
    collect_from_data,
    collect_namespace_state,
)
from collectors.openshift.evidence_normalizer import normalize_evidence


RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
DEMO_DIR = Path(__file__).parent.parent / "demo-definitions"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stargate",
        description="StarGate — centralized validation layer CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # validate-rubric
    p_vr = sub.add_parser("validate-rubric", help="Validate rubric YAML files")
    p_vr.add_argument("path", help="Path to rubric YAML file or directory")

    # evaluate
    p_ev = sub.add_parser("evaluate", help="Evaluate a fixture YAML file")
    p_ev.add_argument("fixture", help="Path to fixture YAML file")
    p_ev.add_argument("--format", choices=["text", "json"], default="text")

    # collect
    p_co = sub.add_parser("collect", help="Collect evidence from a live OpenShift namespace")
    p_co.add_argument("namespace", help="Target namespace")
    p_co.add_argument("--kubeconfig", help="Path to kubeconfig file")
    p_co.add_argument("--stages", help="Comma-separated stages to evaluate (default: all applicable)")
    p_co.add_argument("--output", help="Write collected evidence JSON to directory")
    p_co.add_argument("--format", choices=["text", "json"], default="text", dest="out_format")
    p_co.add_argument("--api-url", help="StarGate API URL to persist results (e.g. http://localhost:8080)")
    p_co.add_argument("--demo-id", help="Demo ID for the run record", default="live-collection")
    p_co.add_argument("--lab-code", help="Lab code (e.g. LB1088) for evidence bundle tracking")
    p_co.add_argument("--cluster-name", help="Cluster name for evidence bundle tracking")

    # collect-dir
    p_cd = sub.add_parser("collect-dir", help="Evaluate evidence from a directory of oc JSON files")
    p_cd.add_argument("directory", help="Path to directory of oc get -o json files")
    p_cd.add_argument("--stages", help="Comma-separated stages to evaluate")
    p_cd.add_argument("--format", choices=["text", "json"], default="text", dest="out_format")
    p_cd.add_argument("--api-url", help="StarGate API URL to persist results (e.g. http://localhost:8080)")
    p_cd.add_argument("--demo-id", help="Demo ID for the run record", default="dir-collection")
    p_cd.add_argument("--lab-code", help="Lab code (e.g. LB1088) for evidence bundle tracking")
    p_cd.add_argument("--cluster-name", help="Cluster name for evidence bundle tracking")

    args = parser.parse_args(argv)

    if args.command == "validate-rubric":
        return _cmd_validate_rubric(args)
    elif args.command == "evaluate":
        return _cmd_evaluate(args)
    elif args.command == "collect":
        return _cmd_collect(args)
    elif args.command == "collect-dir":
        return _cmd_collect_dir(args)
    else:
        parser.print_help()
        return 0


# --- Commands ---

def _cmd_validate_rubric(args) -> int:
    path = Path(args.path)
    if path.is_dir():
        try:
            rubrics = load_rubrics_from_directory(path)
            for r in sorted(rubrics, key=lambda r: r.id):
                criteria_count = len(r.exit_criteria)
                print(f"  {r.id} ({r.version}) — {criteria_count} exit criteria")
            print(f"Validated {len(rubrics)} rubrics.")
            return 0
        except RubricLoadError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    elif path.is_file() and path.suffix in (".yaml", ".yml"):
        try:
            r = load_rubric(path)
            print(f"  {r.id} ({r.version}) — {len(r.exit_criteria)} exit criteria")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        print(f"Error: {path} is not a valid YAML file or directory", file=sys.stderr)
        return 1


def _cmd_evaluate(args) -> int:
    path = Path(args.fixture)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1

    fixture = yaml.safe_load(path.read_text())
    rubrics = _load_all_rubrics()
    run_info = fixture.get("run", {})

    results = []
    any_failed = False

    for stage_def in fixture.get("stages", []):
        stage_id = stage_def["stage_id"]
        evidence = stage_def.get("evidence", {})
        expected = stage_def.get("expected_outcome")

        rubric = rubrics.get(stage_id)
        if not rubric:
            print(f"  [?] {stage_id}: no rubric found", file=sys.stderr)
            continue

        result = evaluate_rubric(rubric, evidence)
        matched = result.outcome.value == expected if expected else None
        icon = _outcome_icon(result.outcome)

        results.append({
            "stage_id": stage_id,
            "outcome": result.outcome.value,
            "failure_class": result.failure_class,
            "message": result.message,
            "expected": expected,
            "matched": matched,
        })

        if args.format == "text":
            line = f"  {icon} {stage_id}: {result.outcome.value}"
            if expected:
                line += " (expected)" if matched else f" (EXPECTED {expected})"
            print(line)
            if result.failure_class:
                print(f"      failure_class: {result.failure_class}")
            if result.outcome == StageOutcome.FAIL:
                print(f"      message: {result.message}")

        if result.outcome == StageOutcome.FAIL:
            any_failed = True

    if args.format == "json":
        print(json.dumps({"run": run_info, "results": results}, indent=2))

    if args.format == "text":
        passed = sum(1 for r in results if r["outcome"] == "pass")
        failed = sum(1 for r in results if r["outcome"] == "fail")
        warned = sum(1 for r in results if r["outcome"] == "warn")
        summary = f"\n{passed} passed, {failed} failed"
        if warned:
            summary += f", {warned} warned"
        print(summary)

    return 1 if any_failed else 0


def _cmd_collect(args) -> int:
    namespace = args.namespace
    kubeconfig = args.kubeconfig
    output_dir = Path(args.output) if args.output else None

    print(f"Collecting evidence from namespace: {namespace}")

    resources = _COLLECT_RESOURCES
    if args.stages:
        requested = set(args.stages.split(","))
        resources = {k: v for k, v in resources.items() if k in requested or v.get("always")}

    collected = []
    for resource_type, config in resources.items():
        oc_args = config["oc_args"]
        try:
            data = _oc_get(namespace, oc_args, kubeconfig)
            if data:
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    out_file = output_dir / f"{resource_type}.json"
                    out_file.write_text(json.dumps(data, indent=2))

                try:
                    evidence = collect_from_data(data)
                    collected.append(evidence)
                    print(f"  [+] {resource_type}: collected ({evidence.resource_kind})")
                except ValueError as e:
                    print(f"  [~] {resource_type}: skipped ({e})")
        except subprocess.CalledProcessError as e:
            print(f"  [X] {resource_type}: oc get failed ({e.returncode})")
        except Exception as e:
            print(f"  [X] {resource_type}: error ({e})")

    if not collected:
        print("\nNo evidence collected.")
        return 1

    rubrics = _load_all_rubrics()
    stages = args.stages.split(",") if args.stages else list(rubrics.keys())

    print(f"\nEvaluating {len(stages)} stages...")
    any_failed = False
    results = []

    for stage_id in stages:
        rubric = rubrics.get(stage_id)
        if not rubric:
            continue

        normalized = normalize_evidence(stage_id, collected)
        result = evaluate_rubric(rubric, normalized)
        icon = _outcome_icon(result.outcome)

        results.append({
            "stage_id": stage_id,
            "outcome": result.outcome.value,
            "failure_class": result.failure_class,
            "message": result.message,
        })

        if args.out_format == "text":
            print(f"  {icon} {stage_id}: {result.outcome.value}")
            if result.failure_class:
                print(f"      failure_class: {result.failure_class}")
                print(f"      message: {result.message}")

        if result.outcome == StageOutcome.FAIL:
            any_failed = True

    # Persist to API if --api-url provided
    run_id = None
    if getattr(args, "api_url", None):
        run_id = _persist_to_api(
            api_url=args.api_url,
            demo_id=args.demo_id,
            namespace=namespace,
            lab_code=getattr(args, "lab_code", None),
            cluster_name=getattr(args, "cluster_name", None),
            collected=collected,
            results=results,
            out_format=args.out_format,
        )

    if args.out_format == "json":
        output = {"namespace": namespace, "results": results}
        if run_id:
            output["run_id"] = run_id
        print(json.dumps(output, indent=2))
    elif args.out_format == "text":
        passed = sum(1 for r in results if r["outcome"] == "pass")
        failed = sum(1 for r in results if r["outcome"] == "fail")
        warned = sum(1 for r in results if r["outcome"] == "warn")
        summary = f"\n{passed} passed, {failed} failed"
        if warned:
            summary += f", {warned} warned"
        print(summary)

    return 1 if any_failed else 0


def _cmd_collect_dir(args) -> int:
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        return 1

    collected = collect_namespace_state(directory)
    if not collected:
        print("No evidence files found.", file=sys.stderr)
        return 1

    is_json = args.out_format == "json"
    if not is_json:
        print(f"Collected {len(collected)} evidence items from {directory}")
        for ev in collected:
            print(f"  {ev.resource_kind}: {ev.resource_name}")

    rubrics = _load_all_rubrics()
    stages = args.stages.split(",") if args.stages else list(rubrics.keys())

    if not is_json:
        print(f"\nEvaluating {len(stages)} stages...")
    any_failed = False
    results = []

    for stage_id in stages:
        rubric = rubrics.get(stage_id)
        if not rubric:
            continue

        normalized = normalize_evidence(stage_id, collected)
        result = evaluate_rubric(rubric, normalized)
        icon = _outcome_icon(result.outcome)

        results.append({
            "stage_id": stage_id,
            "outcome": result.outcome.value,
            "failure_class": result.failure_class,
            "message": result.message,
        })

        if not is_json:
            print(f"  {icon} {stage_id}: {result.outcome.value}")
            if result.failure_class:
                print(f"      failure_class: {result.failure_class}")
                print(f"      message: {result.message}")

        if result.outcome == StageOutcome.FAIL:
            any_failed = True

    # Persist to API if --api-url provided
    run_id = None
    if getattr(args, "api_url", None):
        namespace = directory.name
        run_id = _persist_to_api(
            api_url=args.api_url,
            demo_id=args.demo_id,
            namespace=namespace,
            lab_code=getattr(args, "lab_code", None),
            cluster_name=getattr(args, "cluster_name", None),
            collected=collected,
            results=results,
            out_format=args.out_format if not is_json else "json",
        )

    if is_json:
        output = {"directory": str(directory), "results": results}
        if run_id:
            output["run_id"] = run_id
        print(json.dumps(output, indent=2))
    else:
        passed = sum(1 for r in results if r["outcome"] == "pass")
        failed = sum(1 for r in results if r["outcome"] == "fail")
        warned = sum(1 for r in results if r["outcome"] == "warn")
        summary = f"\n{passed} passed, {failed} failed"
        if warned:
            summary += f", {warned} warned"
        print(summary)

    return 1 if any_failed else 0


# --- API Persistence ---

def _persist_to_api(
    api_url: str,
    demo_id: str,
    namespace: str,
    lab_code: Optional[str],
    cluster_name: Optional[str],
    collected: List[CollectedEvidence],
    results: List[Dict],
    out_format: str,
) -> Optional[str]:
    """Submit evidence and evaluations to the StarGate API. Returns run_id."""
    from cli.api_client import StarGateClient

    client = StarGateClient(api_url)

    if not client.health():
        print("  API not reachable, skipping persistence.", file=sys.stderr)
        return None

    run_resp = client.create_run(
        demo_id=demo_id,
        namespace=namespace,
        lab_code=lab_code,
        cluster_name=cluster_name,
    )
    run_id = run_resp.get("run_id")
    if not run_id:
        print(f"  Failed to create run: {run_resp}", file=sys.stderr)
        return None

    if out_format == "text":
        print(f"\n  Persisting to API ({api_url})...")
        print(f"  Run: {run_id}")

    for r in results:
        stage_id = r["stage_id"]
        client.start_stage(run_id, stage_id)

        for ev in collected:
            client.submit_evidence(
                run_id=run_id,
                stage_id=stage_id,
                evidence_type=ev.resource_kind,
                source=ev.source,
                observed=ev.observed,
                result=r["outcome"],
            )

        client.evaluate_stage(run_id, stage_id, evidence={
            k: v for ev in collected
            for k, v in ev.observed.items()
        })

    if out_format == "text":
        print(f"  Persisted {len(results)} stages with {len(collected)} evidence items each.")
        print(f"  View report: curl {api_url}/runs/{run_id}/report")

    return run_id


# --- Helpers ---

_COLLECT_RESOURCES = {
    "namespace": {"oc_args": ["get", "namespace", "{ns}", "-o", "json"], "always": True},
    "deployment": {"oc_args": ["get", "deployment", "-n", "{ns}", "-o", "json"]},
    "pods": {"oc_args": ["get", "pods", "-n", "{ns}", "-o", "json"]},
    "services": {"oc_args": ["get", "service", "-n", "{ns}", "-o", "json"]},
    "endpoints": {"oc_args": ["get", "endpoints", "-n", "{ns}", "-o", "json"]},
    "routes": {"oc_args": ["get", "route", "-n", "{ns}", "-o", "json"]},
    "events": {"oc_args": ["get", "events", "-n", "{ns}", "-o", "json"]},
    "anarchysubject": {"oc_args": ["get", "anarchysubject", "-n", "{ns}", "-o", "json"]},
}


def _oc_get(namespace: str, oc_args: List[str], kubeconfig: Optional[str] = None) -> Optional[Dict]:
    args = [a.replace("{ns}", namespace) for a in oc_args]
    cmd = ["oc"] + args
    env = None
    if kubeconfig:
        import os
        env = {**os.environ, "KUBECONFIG": kubeconfig}

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, env=env,
    )
    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _load_all_rubrics() -> Dict[str, Rubric]:
    rubrics = {}
    if RUBRIC_DIR.is_dir():
        try:
            for r in load_rubrics_from_directory(RUBRIC_DIR):
                rubrics[r.stage] = r
        except RubricLoadError:
            pass
    return rubrics


def _outcome_icon(outcome: StageOutcome) -> str:
    if outcome == StageOutcome.PASS:
        return "[+]"
    elif outcome == StageOutcome.WARN:
        return "[~]"
    return "[X]"


if __name__ == "__main__":
    sys.exit(main())
