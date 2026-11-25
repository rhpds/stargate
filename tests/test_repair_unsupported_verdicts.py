"""Repairing verdicts that the report text does not substantiate.

The defect: verdicts were invented from the appended adjudication summary and
from upper-case prose, for investigations that never stated one. These tests pin
the repair to the safety properties that matter — it nulls only the
unsubstantiated rows, leaves a disagreeing report alone, touches nothing else in
`trust_dimensions`, writes nothing on a dry run, and is idempotent.
"""

import io
import json

import pytest

from scripts.repair_unsupported_verdicts import repair


def _inv(db, job_id, analysis, trust=None, status="complete"):
    from db.models import InvestigationRecord
    from datetime import datetime, timezone
    db.add(InvestigationRecord(
        job_id=job_id, lab_code="sandbox-ab12c-ocp4", cluster="ocp-east",
        failure_class="pods_crashlooping", status=status,
        analysis=analysis, tool_calls=[],
        trust_dimensions=trust,
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()


def _trust(db, job_id):
    from db.models import InvestigationRecord
    return db.query(InvestigationRecord).filter_by(job_id=job_id).one().trust_dimensions


# The real analysis of inv-5e0ae4cc: no report sections, a verdict only in the
# appended review block.
ADJUDICATION_ONLY = """
Let me gather more evidence before concluding — I need the AgnosticV config, VM details, and recent changes.

### Model adjudication — review only
Status: needs_human_review. Human verification is still required.
Blind reviewer 2: ACTIONABLE (75% model confidence).
Judge: disputed. Insufficient root cause evidence
"""

# id=2957: the adjective attached to a PVC, inside ordinary remediation prose.
PROSE_ONLY = """
## 3. Remediation Strategy

**For the postgres read-only PVC (primary — ACTIONABLE):**
The Ceph RBD volume needs to be investigated at the storage layer.
"""

LEGITIMATE = """## Investigation: sandbox-ab12c-ocp4

### 2. Root Cause

The deployment references image tag `latest` that was pruned from the registry.

### 6. Verdict

> **TRANSIENT**

Confidence: 0.72
"""


class TestUnsupportedVerdicts:
    def test_adjudication_verdict_is_nulled(self, db):
        _inv(db, "inv-adj", ADJUDICATION_ONLY,
             trust={"verdict": "ACTIONABLE", "confidence": None,
                    "evidence_sufficient": True})

        report = repair(db, apply=True)

        trust = _trust(db, "inv-adj")
        assert trust["verdict"] is None
        # The other fields are not part of the defect and must survive.
        assert trust["evidence_sufficient"] is True
        assert report["unsupported"] == 1 and report["changed"] == 1

    def test_upper_case_prose_verdict_is_nulled(self, db):
        _inv(db, "inv-prose", PROSE_ONLY, trust={"verdict": "ACTIONABLE"})

        repair(db, apply=True)

        assert _trust(db, "inv-prose")["verdict"] is None

    def test_a_report_that_states_a_verdict_is_kept(self, db):
        _inv(db, "inv-ok", LEGITIMATE, trust={"verdict": "TRANSIENT"})

        report = repair(db, apply=True)

        assert _trust(db, "inv-ok")["verdict"] == "TRANSIENT"
        assert report["unsupported"] == 0
        assert report["with_verdict"] == 1

    def test_a_disagreeing_report_is_left_alone(self, db):
        _inv(db, "inv-mismatch", LEGITIMATE, trust={"verdict": "ACTIONABLE"})

        report = repair(db, apply=True)

        assert _trust(db, "inv-mismatch")["verdict"] == "ACTIONABLE"
        assert report["disagreed"] == 1
        assert report["changed"] == 0

    def test_rows_without_a_verdict_are_out_of_scope(self, db):
        _inv(db, "inv-empty", ADJUDICATION_ONLY)

        report = repair(db, apply=True)

        assert _trust(db, "inv-empty") is None
        assert report["with_verdict"] == 0 and report["changed"] == 0

    def test_incomplete_rows_are_out_of_scope(self, db):
        _inv(db, "inv-err", ADJUDICATION_ONLY,
             trust={"verdict": "ACTIONABLE"}, status="error")

        report = repair(db, apply=True)

        assert _trust(db, "inv-err")["verdict"] == "ACTIONABLE"
        assert report["examined"] == 0


class TestApplySemantics:
    def test_dry_run_writes_nothing(self, db):
        _inv(db, "inv-dry", ADJUDICATION_ONLY, trust={"verdict": "ACTIONABLE"})

        report = repair(db, apply=False)

        assert report["unsupported"] == 1
        assert _trust(db, "inv-dry")["verdict"] == "ACTIONABLE"

    def test_apply_is_idempotent(self, db):
        _inv(db, "inv-idem", ADJUDICATION_ONLY, trust={"verdict": "ACTIONABLE"})

        first = repair(db, apply=True)
        after_first = _trust(db, "inv-idem")
        second = repair(db, apply=True)

        assert first["changed"] == 1
        assert second["changed"] == 0
        assert _trust(db, "inv-idem") == after_first

    def test_apply_emits_a_rollback_record_per_changed_row(self, db):
        _inv(db, "inv-rb", ADJUDICATION_ONLY,
             trust={"verdict": "ACTIONABLE", "evidence_sufficient": True})
        buf = io.StringIO()

        repair(db, apply=True, backup=buf)

        lines = [json.loads(line) for line in buf.getvalue().splitlines()]
        assert len(lines) == 1
        assert lines[0]["job_id"] == "inv-rb"
        assert lines[0]["before"]["verdict"] == "ACTIONABLE"
        assert lines[0]["after"]["verdict"] is None
        assert lines[0]["after"]["evidence_sufficient"] is True

    def test_list_file_holds_the_affected_ids(self, db):
        _inv(db, "inv-a", ADJUDICATION_ONLY, trust={"verdict": "ACTIONABLE"})
        _inv(db, "inv-b", LEGITIMATE, trust={"verdict": "TRANSIENT"})
        ids = io.StringIO()

        repair(db, apply=False, list_file=ids)

        written = ids.getvalue().split()
        assert len(written) == 1


class TestDeployedParserGuard:
    def test_refuses_an_image_that_predates_the_fix(self, db, monkeypatch):
        from tasks import maintenance
        monkeypatch.delattr(maintenance, "_strip_adjudication_summary")

        with pytest.raises(SystemExit):
            repair(db, apply=False)


class TestCliFlags:
    def test_dry_run_and_apply_are_mutually_exclusive(self):
        from scripts.repair_unsupported_verdicts import main

        with pytest.raises(SystemExit):
            main(["--dry-run", "--apply"])
