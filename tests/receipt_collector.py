"""Receipt collector — structured test receipts for scenario matrix validation.

Each receipt proves a specific scenario × pipeline × gate mode combination
produced the expected outcome. Receipts are JSON-serializable and written
to test-receipts/ for audit.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RECEIPTS_DIR = Path(__file__).parent.parent / "test-receipts"


def create_receipt(
    scenario: str,
    pipeline: str,
    gate_mode: str = "normal",
    rubric_outcomes: Optional[Dict[str, str]] = None,
    rubric_match: bool = True,
    recommendations_produced: Optional[List[str]] = None,
    recommendations_expected: Optional[List[str]] = None,
    policy_match: bool = True,
    routing_decision: Optional[str] = None,
    routing_reason: Optional[str] = None,
    gaudi_utilization: Optional[float] = None,
    xeon6_utilization: Optional[float] = None,
    substrate_recommendation: Optional[Dict] = None,
    events_emitted: int = 0,
    systemic_detected: bool = False,
    max_priority: float = 0,
    action_proposed: Optional[str] = None,
    confidence: float = 1.0,
    action_executed: bool = False,
    action_reason: Optional[str] = None,
    audit_entry_id: Optional[int] = None,
    passed: bool = True,
) -> Dict[str, Any]:
    """Create a structured test receipt."""
    return {
        "test_id": f"{scenario}/{pipeline}/{gate_mode}",
        "scenario": scenario,
        "pipeline": pipeline,
        "gate_mode": gate_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence_source": "synthetic",
        "rubric_outcomes": rubric_outcomes or {},
        "rubric_match": rubric_match,
        "recommendations_produced": recommendations_produced or [],
        "recommendations_expected": recommendations_expected or [],
        "policy_match": policy_match,
        "routing_decision": routing_decision,
        "routing_reason": routing_reason,
        "gaudi_utilization": gaudi_utilization,
        "xeon6_utilization": xeon6_utilization,
        "substrate_recommendation": substrate_recommendation,
        "events_emitted": events_emitted,
        "systemic_detected": systemic_detected,
        "max_priority": max_priority,
        "action_proposed": action_proposed,
        "confidence": confidence,
        "action_executed": action_executed,
        "action_reason": action_reason,
        "audit_entry_id": audit_entry_id,
        "pass": passed,
    }


def save_receipt(receipt: Dict[str, Any]) -> str:
    """Save a receipt to test-receipts/ as JSON. Returns filepath."""
    RECEIPTS_DIR.mkdir(exist_ok=True)
    filename = f"{receipt['test_id'].replace('/', '_')}.json"
    filepath = RECEIPTS_DIR / filename
    with open(filepath, "w") as f:
        json.dump(receipt, f, indent=2)
    return str(filepath)


def generate_summary(receipts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a summary report from all receipts."""
    passed = sum(1 for r in receipts if r["pass"])
    failed = sum(1 for r in receipts if not r["pass"])
    return {
        "total": len(receipts),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / max(len(receipts), 1) * 100, 1),
        "scenarios": list(set(r["scenario"] for r in receipts)),
        "pipelines": list(set(r["pipeline"] for r in receipts)),
        "gate_modes": list(set(r["gate_mode"] for r in receipts)),
        "failures": [r["test_id"] for r in receipts if not r["pass"]],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_summary(receipts: List[Dict[str, Any]]) -> str:
    """Save summary report to test-receipts/summary.json."""
    RECEIPTS_DIR.mkdir(exist_ok=True)
    summary = generate_summary(receipts)
    filepath = RECEIPTS_DIR / "summary.json"
    with open(filepath, "w") as f:
        json.dump(summary, f, indent=2)
    return str(filepath)
