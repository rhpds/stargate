"""Can we diagnose what we report, and who owns it?"""

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def _fail(db, run_id, cls="pods_not_ready", lab="sandbox-a", minutes=10):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=run_id, stage_id="deployment-ready", outcome="fail", failure_class=cls,
        lab_code=lab, cluster_name="ocpv08", evaluated_at=NOW - timedelta(minutes=minutes),
    ))
    db.commit()


def _evidence(db, run_id, kind, observed=None):
    from db.models import EvidenceRecord
    from uuid import uuid4
    db.add(EvidenceRecord(
        evidence_id=f"ev-{uuid4().hex[:10]}", run_id=run_id, stage_id="deployment-ready",
        type=kind, source="test", observed=observed or {}, result="fail",
        timestamp=NOW - timedelta(minutes=5),
    ))
    db.commit()


class TestEvidenceCompleteness:
    def test_reports_the_share_of_diagnosable_runs(self, db):
        from db.repository import evidence_completeness

        _fail(db, "r1")
        _fail(db, "r2")
        _evidence(db, "r1", "PodList")
        _evidence(db, "r1", "Deployment")
        _evidence(db, "r2", "Deployment")  # missing PodList

        report = evidence_completeness(db, hours=24)
        row = report["classes"][0]

        assert row["failure_class"] == "pods_not_ready"
        assert row["failing_runs"] == 2
        assert row["covered_runs"] == 1
        assert row["coverage_pct"] == 50


class TestFailureOwners:
    def test_groups_labs_by_namespace_owner(self, db):
        from db.repository import failure_owners

        _evidence(db, "scan-1", "Namespace", {
            "name": "sandbox-a", "owner": "alice", "owner_email": "alice@example.com",
            "catalog_item": "zt-rhel-bu-lab-developer-cnv",
        })
        _fail(db, "r1", lab="sandbox-a")
        _fail(db, "r2", lab="sandbox-b")  # no namespace evidence → unattributed

        report = failure_owners(db, hours=24)
        by_owner = {row["owner"]: row for row in report["owners"]}

        assert by_owner["alice"]["labs"] == 1
        assert by_owner["(unattributed)"]["labs"] == 1
