"""Pipeline rubric evaluator — tracks each failure class through the
cross-system proof pipeline (detect → hypothesize → classify → recommend → prove → trust).

Evaluates TDD/EDD/CDD/BDD dimensions at each stage across Deepfield,
GeoLux, and StarGate. Produces a matrix receipt.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.pipeline_rubric")

_PERSISTENT_DIR = Path("/opt/app-root/src/scan-history")
PIPELINE_MATRIX_FILE = _PERSISTENT_DIR / "pipeline-matrix.json" if _PERSISTENT_DIR.is_dir() else Path(__file__).parent.parent / "test-receipts" / "pipeline-matrix.json"

STAGES = ["detect", "hypothesize", "classify", "recommend", "prove", "trust"]
DIMENSIONS = ["tdd", "edd", "cdd", "bdd"]
OUTCOMES = {"green": 2, "yellow": 1, "red": 0}


class PipelineRubricTracker:
    def __init__(self, path: Path = PIPELINE_MATRIX_FILE):
        self._path = path
        self._data = self._load()

    def _load(self) -> Dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {
            "type": "pipeline-rubric-matrix",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "failure_classes": {},
        }

    def _save(self):
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def _get_fc(self, failure_class: str) -> Dict:
        if failure_class not in self._data["failure_classes"]:
            self._data["failure_classes"][failure_class] = {
                "current_stage": None,
                "stages": {stage: {
                    "status": "not_started",
                    "dimensions": {dim: {"outcome": "red", "evidence": []} for dim in DIMENSIONS},
                    "system": None,
                    "completed_at": None,
                } for stage in STAGES},
            }
        return self._data["failure_classes"][failure_class]

    def record_stage(self, failure_class: str, stage: str, system: str,
                     dimensions: Dict[str, str], evidence: Dict[str, List[str]] = None):
        """Record a stage evaluation.

        dimensions: {"tdd": "green", "edd": "yellow", "cdd": "green", "bdd": "red"}
        evidence: {"tdd": ["Signal collected", "Normalized"], "edd": ["Matched pattern"]}
        """
        fc = self._get_fc(failure_class)
        stage_data = fc["stages"][stage]
        stage_data["system"] = system
        stage_data["completed_at"] = datetime.now(timezone.utc).isoformat()

        all_pass = True
        for dim in DIMENSIONS:
            outcome = dimensions.get(dim, "red")
            stage_data["dimensions"][dim]["outcome"] = outcome
            stage_data["dimensions"][dim]["evidence"] = (evidence or {}).get(dim, [])
            if OUTCOMES.get(outcome, 0) < OUTCOMES["green"]:
                all_pass = False

        stage_data["status"] = "passed" if all_pass else "gated"
        fc["current_stage"] = stage

        self._save()

    def get_matrix(self) -> Dict:
        return self._data

    def get_fc_summary(self, failure_class: str) -> Dict:
        fc = self._get_fc(failure_class)
        summary = {"failure_class": failure_class, "current_stage": fc["current_stage"], "stages": {}}
        for stage in STAGES:
            sd = fc["stages"][stage]
            dims = {d: sd["dimensions"][d]["outcome"] for d in DIMENSIONS}
            summary["stages"][stage] = {
                "status": sd["status"],
                "system": sd["system"],
                "dimensions": dims,
                "overall": "green" if all(v == "green" for v in dims.values()) else
                           "yellow" if any(v == "yellow" for v in dims.values()) else "red",
            }
        return summary

    def get_overview(self) -> Dict:
        fcs = self._data["failure_classes"]
        total = len(fcs)
        stages_reached = {}
        for stage in STAGES:
            stages_reached[stage] = sum(
                1 for fc in fcs.values()
                if fc["stages"][stage]["status"] in ("passed", "gated")
            )
        return {
            "total_failure_classes": total,
            "stages_reached": stages_reached,
            "fully_proven": sum(
                1 for fc in fcs.values()
                if fc["stages"]["trust"]["status"] == "passed"
            ),
        }
