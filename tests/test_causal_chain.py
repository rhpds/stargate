"""Tests for the causal-chain artifact (the smoking-gun assembly).

Full chain: symptom eval -> investigation with evidence and diagnosis ->
queued action -> executed remediation -> verification eval. Partial chains
report their missing legs honestly.
"""

from datetime import datetime, timedelta, timezone

from db.models import (
    EvaluationRecord, InvestigationRecord, PendingAction, RemediationRecord,
)
from db.repository import build_causal_chain


NOW = datetime.now(timezone.utc)


def _full_chain(db, *, with_verification=True):
    symptom = EvaluationRecord(
        run_id="scan-1", stage_id="cluster-health", lab_code="sandbox-smoke",
        cluster_name="ocpv05", outcome="fail", failure_class="pods_crashlooping",
        message="pod restarted 14 times", evaluated_at=NOW - timedelta(hours=4),
    )
    db.add(symptom)
    db.flush()
    inv = InvestigationRecord(
        job_id="job-chain", lab_code="sandbox-smoke", cluster="ocpv05",
        namespace="sandbox-smoke", failure_class="pods_crashlooping",
        trigger_type="auto_anomalous", status="complete",
        triggering_eval_id=symptom.id, created_at=NOW - timedelta(hours=3),
        root_cause="database dependency unreachable", remediation_suggestion="restart the deployment",
        trust_dimensions={"verdict": "ACTIONABLE", "confidence": 85},
        tool_calls=[{"tool": "oc_read", "args": {"command": "get pods"}, "result_preview": "CrashLoopBackOff", "iteration": 1}],
    )
    db.add(inv)
    db.flush()
    action = PendingAction(
        action_type="cleanup_stuck", target="sandbox-smoke", proposed_by="investigation",
        parameters={"investigation_id": inv.id, "job_id": inv.job_id,
                    "triggering_eval_id": symptom.id, "failure_class": "pods_crashlooping",
                    "remediation_suggestion": "restart the deployment"},
        confidence=0.8, status="executed", proposed_at=NOW - timedelta(hours=2),
    )
    db.add(action)
    remediation = RemediationRecord(
        run_id="sandbox-smoke", stage_id=str(symptom.id), failure_class="pods_crashlooping",
        remediation_id="cleanup_stuck", action_taken="restart the deployment",
        applied_at=NOW - timedelta(hours=1), applied_by="admin:admin",
        notes=f"investigation:{inv.id}", resolved=None,
    )
    db.add(remediation)
    if with_verification:
        verification = EvaluationRecord(
            run_id="scan-2", stage_id="cluster-health", lab_code="sandbox-smoke",
            cluster_name="ocpv05", outcome="pass", failure_class=None,
            message="healthy", evaluated_at=NOW - timedelta(minutes=30),
        )
        db.add(verification)
        db.flush()
        remediation.verification_eval_id = verification.id
        remediation.resolved = True
    db.commit()
    return inv


class TestCausalChain:
    def test_full_chain_assembles_and_completes(self, db):
        inv = _full_chain(db)
        chain = build_causal_chain(db, investigation_id=inv.id)

        assert chain["found"] is True
        assert chain["chain_complete"] is True
        assert chain["missing_legs"] == []
        # T0 symptom linked by lineage
        assert chain["symptom"]["failure_class"] == "pods_crashlooping"
        assert chain["symptom"]["outcome"] == "fail"
        # Evidence collected by the agent
        assert chain["evidence_count"] == 1
        assert chain["evidence"][0]["tool"] == "oc_read"
        # Diagnosis with verdict
        assert chain["diagnosis"]["root_cause"] == "database dependency unreachable"
        assert chain["diagnosis"]["verdict"] == "ACTIONABLE"
        # Action and remediation
        assert chain["action"]["action_type"] == "cleanup_stuck"
        assert chain["remediation"]["remediation_id"] == "cleanup_stuck"
        # T2 verification: the passing eval
        assert chain["verification"]["outcome"] == "pass"

    def test_chain_without_verification_reports_missing_legs(self, db):
        inv = _full_chain(db, with_verification=False)
        chain = build_causal_chain(db, investigation_id=inv.id)

        assert chain["found"] is True
        assert chain["chain_complete"] is False
        assert "verification_eval" in chain["missing_legs"]
        assert chain["verification"] is None
        # The rest of the chain is still assembled
        assert chain["symptom"] is not None
        assert chain["remediation"] is not None

    def test_namespace_lookup_finds_latest_investigation(self, db):
        inv = _full_chain(db)
        chain = build_causal_chain(db, namespace="sandbox-smoke")
        assert chain["found"] is True
        assert chain["investigation"]["id"] == inv.id

    def test_missing_investigation_is_honest(self, db):
        chain = build_causal_chain(db, namespace="never-seen")
        assert chain["found"] is False

    def test_requires_a_lookup_key(self, db):
        import pytest
        with pytest.raises(ValueError):
            build_causal_chain(db)

    def test_endpoint_serves_the_chain(self, db, client):
        inv = _full_chain(db)
        resp = client.get(
            f"/dashboard/causal-chain?investigation_id={inv.id}",
            headers={"X-API-Key": "test-key-for-ci"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chain_complete"] is True
        assert body["verification"]["outcome"] == "pass"
