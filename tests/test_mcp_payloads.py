"""Large MCP payloads must stay parseable.

get_proof_matrix sliced the 1.4 MB proof matrix at 30 KB, returning invalid
JSON and hiding the gate; the causal chain did the same at 20 KB.
"""

import json

from api.mcp_server import bounded_json, compact_proof_matrix


class TestProofMatrix:
    def test_drops_history_and_counts_gates(self):
        data = {
            "type": "proof-matrix", "namespace": "stargate-test", "cluster": "infra01",
            "failure_classes": {
                "pods_crashlooping": {
                    "status": "PROVEN", "proof_type": "remediation",
                    "cycles_completed": 6, "cycles_failed": 0,
                    "consecutive_passes": 6, "gate": "full_auto",
                    "last_run": "2026-11-19T00:00:00Z",
                    "history": [{"big": "x" * 500}] * 50,
                    "cycle_results": [{"big": "y" * 500}] * 50,
                },
                "pvc_pending": {
                    "status": "DETECTED", "proof_type": "investigation",
                    "gate": "investigation_proven",
                },
            },
        }

        compact = compact_proof_matrix(data)

        assert compact["summary"]["classes"] == 2
        assert compact["summary"]["remediation_proven"] == 1
        assert compact["summary"]["detection_proven"] == 1
        assert "history" not in compact["failure_classes"]["pods_crashlooping"]
        assert "cycle_results" not in compact["failure_classes"]["pods_crashlooping"]
        assert len(json.dumps(compact)) < 2000


class TestBoundedJson:
    def test_never_returns_invalid_json(self):
        payload = {"evidence": ["x" * 5000 for _ in range(10)]}
        text = bounded_json(payload, limit=500)

        parsed = json.loads(text)
        assert parsed["truncated"] is True
        assert len(text) < 20000

    def test_small_payload_is_untouched(self):
        payload = {"ok": True}
        assert json.loads(bounded_json(payload)) == payload
