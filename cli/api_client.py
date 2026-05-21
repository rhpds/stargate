"""Lightweight HTTP client for submitting evidence and evaluations to the StarGate API."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError


class StarGateClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, data: dict) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except URLError as e:
            print(f"  API error: {e}", file=sys.stderr)
            return {"error": str(e)}

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = Request(url)
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except URLError as e:
            return {"error": str(e)}

    def create_run(
        self,
        demo_id: str,
        namespace: str,
        rubric_version: str = "v0.1.0",
        run_id: Optional[str] = None,
        lab_code: Optional[str] = None,
        cluster_name: Optional[str] = None,
    ) -> dict:
        data = {
            "demo_id": demo_id,
            "namespace": namespace,
            "requested_by": "stargate-cli",
            "rubric_version": rubric_version,
        }
        if run_id:
            data["run_id"] = run_id
        if lab_code:
            data["lab_code"] = lab_code
        if cluster_name:
            data["cluster_name"] = cluster_name
        return self._post("/runs", data)

    def start_stage(self, run_id: str, stage_id: str) -> dict:
        return self._post(f"/runs/{run_id}/stages/{stage_id}/start", {})

    def submit_evidence(
        self,
        run_id: str,
        stage_id: str,
        evidence_type: str,
        source: str,
        observed: Dict,
        result: str,
    ) -> dict:
        return self._post(f"/runs/{run_id}/stages/{stage_id}/evidence", {
            "type": evidence_type,
            "source": source,
            "observed": observed,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def evaluate_stage(self, run_id: str, stage_id: str, evidence: Optional[Dict] = None) -> dict:
        data = {}
        if evidence:
            data["evidence"] = evidence
        return self._post(f"/runs/{run_id}/stages/{stage_id}/evaluate", data)

    def get_report(self, run_id: str) -> dict:
        return self._get(f"/runs/{run_id}/report")

    def get_bundle(self, run_id: str) -> dict:
        return self._get(f"/runs/{run_id}/bundle")

    def health(self) -> bool:
        result = self._get("/health")
        return result.get("status") == "ok"
