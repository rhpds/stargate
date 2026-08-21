"""Proof tracker — tracks remediation proof state per failure class.

Gate progression: UNTESTED -> INJECTED -> DETECTED -> REMEDIATED -> VERIFIED -> PROVEN
Each transition requires evidence.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.proof_tracker")

_PERSISTENT_DIR = Path("/opt/app-root/src/scan-history")
PROOF_FILE = _PERSISTENT_DIR / "proof-matrix.json" if _PERSISTENT_DIR.is_dir() else Path(__file__).parent.parent / "test-receipts" / "proof-matrix.json"
PROVEN_THRESHOLD = 3  # consecutive successful cycles to reach PROVEN


class ProofTracker:
    def __init__(self, path: Path = PROOF_FILE):
        self._path = path
        self._data = self._load()

    def _load(self) -> Dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {
            "type": "proof-matrix",
            "namespace": os.environ.get("STARGATE_TEST_NAMESPACE", "stargate-test"),
            "cluster": "infra01",
            "failure_classes": {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save(self):
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def _get_fc(self, failure_class: str) -> Dict:
        if failure_class not in self._data["failure_classes"]:
            self._data["failure_classes"][failure_class] = {
                "status": "UNTESTED",
                "proof_type": "remediation",
                "cycles_completed": 0,
                "cycles_failed": 0,
                "consecutive_passes": 0,
                "gate": "manual",
                "last_run": None,
                "history": [],
            }
        return self._data["failure_classes"][failure_class]

    def record_injection(self, failure_class: str, evidence: Dict):
        fc = self._get_fc(failure_class)
        fc["status"] = "INJECTED"
        fc["last_run"] = datetime.now(timezone.utc).isoformat()
        fc["history"].append({"event": "injected", "ts": fc["last_run"], "evidence": evidence})
        self._save()

    def record_detection(self, failure_class: str, detected_class: str, source: str = "stargate"):
        fc = self._get_fc(failure_class)
        fc["status"] = "DETECTED"
        correct = detected_class == failure_class
        fc["history"].append({
            "event": "detected", "ts": datetime.now(timezone.utc).isoformat(),
            "detected_class": detected_class, "correct": correct, "source": source,
        })
        self._save()

    def record_remediation(self, failure_class: str, action: str, success: bool, evidence: Dict):
        fc = self._get_fc(failure_class)
        fc["status"] = "REMEDIATED" if success else "FAILED"
        fc["history"].append({
            "event": "remediated", "ts": datetime.now(timezone.utc).isoformat(),
            "action": action, "success": success, "evidence": evidence,
        })
        self._save()

    def record_verification(self, failure_class: str, clean: bool, evidence: Dict):
        fc = self._get_fc(failure_class)
        if clean:
            fc["status"] = "VERIFIED"
            fc["cycles_completed"] += 1
            fc["consecutive_passes"] += 1
            if fc["consecutive_passes"] >= PROVEN_THRESHOLD:
                fc["status"] = "PROVEN"
                fc["gate"] = "full_auto"
            elif fc["consecutive_passes"] >= 1:
                fc["gate"] = "low_risk_auto"
        else:
            fc["status"] = "FAILED"
            fc["cycles_failed"] += 1
            fc["consecutive_passes"] = 0
        fc["history"].append({
            "event": "verified", "ts": datetime.now(timezone.utc).isoformat(),
            "clean": clean, "evidence": evidence,
        })
        self._save()

    def record_investigation_verified(self, failure_class: str, detection_correct: bool, evidence: Dict):
        """For investigation-type proofs: success = correct detection, not remediation fix."""
        fc = self._get_fc(failure_class)
        fc["proof_type"] = "investigation"
        if detection_correct:
            fc["status"] = "VERIFIED"
            fc["cycles_completed"] += 1
            fc["consecutive_passes"] += 1
            if fc["consecutive_passes"] >= PROVEN_THRESHOLD:
                fc["status"] = "PROVEN"
                fc["gate"] = "investigation_proven"
        else:
            fc["status"] = "FAILED"
            fc["cycles_failed"] += 1
            fc["consecutive_passes"] = 0
        fc["history"].append({
            "event": "investigation_verified", "ts": datetime.now(timezone.utc).isoformat(),
            "detection_correct": detection_correct, "evidence": evidence,
        })
        self._save()

    def record_cycle_result(self, failure_class: str, result: Dict):
        """Store a complete proof cycle result with command-level detail."""
        fc = self._get_fc(failure_class)
        # Keep last 5 full results to avoid unbounded growth
        if "cycle_results" not in fc:
            fc["cycle_results"] = []
        fc["cycle_results"] = fc["cycle_results"][-4:] + [result]
        self._save()

    def get_matrix(self) -> Dict:
        return self._data

    def get_status(self, failure_class: str) -> str:
        return self._get_fc(failure_class)["status"]

    def get_summary(self) -> Dict:
        fcs = self._data["failure_classes"]
        return {
            "total": len(fcs),
            "proven": sum(1 for fc in fcs.values() if fc["status"] == "PROVEN"),
            "verified": sum(1 for fc in fcs.values() if fc["status"] == "VERIFIED"),
            "untested": sum(1 for fc in fcs.values() if fc["status"] == "UNTESTED"),
            "failed": sum(1 for fc in fcs.values() if fc["status"] == "FAILED"),
        }
