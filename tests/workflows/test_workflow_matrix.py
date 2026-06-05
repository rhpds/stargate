"""Workflow coverage matrix — generates a receipt showing test status per workflow."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

WORKFLOWS = [
    ("scanner", "tests/workflows/test_wf_scanner.py"),
    ("event_pipeline", "tests/workflows/test_wf_event_pipeline.py"),
    ("remediation", "tests/workflows/test_wf_remediation.py"),
    ("geolux", "tests/workflows/test_wf_geolux.py"),
    ("deepfield", "tests/workflows/test_wf_deepfield.py"),
    ("demolition", "tests/workflows/test_wf_demolition.py"),
    ("labagator", "tests/workflows/test_wf_labagator.py"),
    ("corpus_mining", "tests/workflows/test_wf_corpus.py"),
    ("notifications", "tests/workflows/test_wf_notifications.py"),
]


def test_generate_workflow_matrix():
    """Run all workflow tests and generate a coverage receipt."""
    results = []

    for name, test_file in WORKFLOWS:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=no", "-q"],
            capture_output=True, text=True, timeout=60,
        )
        lines = result.stdout.strip().split("\n")
        summary_line = lines[-1] if lines else ""

        passed = 0
        failed = 0
        for line in lines:
            if "PASSED" in line:
                passed += 1
            elif "FAILED" in line:
                failed += 1

        status = "PASS" if result.returncode == 0 else "FAIL"
        results.append({
            "workflow": name,
            "test_file": test_file,
            "status": status,
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "summary": summary_line,
        })

    receipt = {
        "type": "workflow-matrix",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_workflows": len(results),
        "passing": sum(1 for r in results if r["status"] == "PASS"),
        "failing": sum(1 for r in results if r["status"] == "FAIL"),
        "total_tests": sum(r["total"] for r in results),
        "workflows": results,
    }

    receipt_path = Path(__file__).parent.parent.parent / "test-receipts" / "workflow-matrix.json"
    receipt_path.parent.mkdir(exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2))

    print(f"\n{'Workflow':25s} {'Status':8s} {'Passed':>8s} {'Failed':>8s}")
    print("-" * 55)
    for r in results:
        print(f"{r['workflow']:25s} {r['status']:8s} {r['passed']:>8d} {r['failed']:>8d}")
    print(f"\nReceipt: {receipt_path}")

    assert receipt["failing"] == 0, f"{receipt['failing']} workflows have failing tests"
