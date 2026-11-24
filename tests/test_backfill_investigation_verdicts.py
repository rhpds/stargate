"""Backfilling verdicts on investigations that shipped before the extractor fix.

The regression: 45% of completed investigations stored a NULL verdict because
the agent writes `### 6. Verdict` followed by a blank line and `> **TRANSIENT**`,
and the old pattern only accepted the enum beside the word. These tests pin the
backfill to the same parser the live path now uses, and pin its two safety
properties: it never overwrites a populated field, and a dry run writes nothing.
"""

import io
import json

from scripts.backfill_investigation_verdicts import backfill


def _inv(db, job_id, analysis, trust=None, tool_calls=None, status="complete"):
    from db.models import InvestigationRecord
    from datetime import datetime, timezone
    db.add(InvestigationRecord(
        job_id=job_id, lab_code="sandbox-ab12c-ocp4", cluster="ocp-east",
        failure_class="pods_crashlooping", status=status,
        analysis=analysis, tool_calls=tool_calls or [],
        trust_dimensions=trust,
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()


def _trust(db, job_id):
    from db.models import InvestigationRecord
    return db.query(InvestigationRecord).filter_by(job_id=job_id).one().trust_dimensions


BLOCKQUOTE = """## Investigation: sandbox-ab12c-ocp4

### 2. Root Cause

The deployment references image tag `latest` that was pruned from the registry.

### 6. Verdict

> **TRANSIENT**

Confidence: 0.72
"""

# What `_evidence_sufficient` wants: at least five calls, covering the
# failure-class checklist (oc_read, evaluations, lab identity, resolution
# history). No storage tool, since this failure class is pods_crashlooping.
CALLS = [
    {"tool": "oc_read", "args": {}, "iteration": 0},
    {"tool": "query_evaluations", "args": {}, "iteration": 1},
    {"tool": "get_lab_identity", "args": {}, "iteration": 2},
    {"tool": "get_resolution_history", "args": {}, "iteration": 3},
    {"tool": "oc_read", "args": {}, "iteration": 4},
]


class TestVerdictBackfill:
    def test_blockquote_verdict_is_recovered_with_confidence(self, db):
        _inv(db, "inv-bq", BLOCKQUOTE)

        report = backfill(db, apply=True)

        trust = _trust(db, "inv-bq")
        assert trust["verdict"] == "TRANSIENT"
        assert trust["confidence"] == 0.72
        assert report["verdict"] == 1 and report["confidence"] == 1

    def test_preexisting_verdict_is_never_overwritten(self, db):
        _inv(db, "inv-keep", BLOCKQUOTE, trust={"verdict": "ACTIONABLE", "confidence": 0.9})

        report = backfill(db, apply=True)

        assert _trust(db, "inv-keep") == {"verdict": "ACTIONABLE", "confidence": 0.9}
        assert report["examined"] == 1
        assert report["scanned"] == 0, "rows that already have a verdict stay out of scope"

    def test_analysis_without_a_verdict_stays_null(self, db):
        _inv(db, "inv-none", "### 2. Root Cause\n\nPod was evicted under memory pressure.")

        report = backfill(db, apply=True)

        assert _trust(db, "inv-none") is None
        assert report["changed"] == 0

    def test_prose_does_not_invent_a_verdict(self, db):
        _inv(db, "inv-prose",
             "### 2. Root Cause\n\nThis looks like a transient network blip, "
             "but we could not confirm it.")

        backfill(db, apply=True)

        assert _trust(db, "inv-prose") is None

    def test_error_investigations_are_out_of_scope(self, db):
        _inv(db, "inv-err", BLOCKQUOTE, status="error")

        report = backfill(db, apply=True)

        assert _trust(db, "inv-err") is None
        assert report["examined"] == 0


class TestEvidenceSufficiency:
    def test_evidence_is_recomputed_from_stored_tool_calls(self, db):
        _inv(db, "inv-ev", BLOCKQUOTE, trust={"verdict": None, "evidence_sufficient": False},
             tool_calls=CALLS)

        report = backfill(db, apply=True)

        assert _trust(db, "inv-ev")["evidence_sufficient"] is True
        assert report["evidence"] == 1

    def test_thin_tool_calls_leave_evidence_false(self, db):
        _inv(db, "inv-thin", BLOCKQUOTE, trust={"verdict": None}, tool_calls=CALLS[:2])

        report = backfill(db, apply=True)

        # Nothing to correct: the field was absent and the derived answer is
        # also "not sufficient", so it is not invented.
        assert _trust(db, "inv-thin").get("evidence_sufficient") is not True
        assert report["evidence"] == 0


class TestApplySemantics:
    def test_dry_run_writes_nothing_and_rolls_back(self, db):
        _inv(db, "inv-dry", BLOCKQUOTE, trust={"verdict": None})

        report = backfill(db, apply=False)

        assert report["changed"] == 1
        assert _trust(db, "inv-dry") == {"verdict": None}

    def test_apply_is_idempotent(self, db):
        _inv(db, "inv-idem", BLOCKQUOTE)
        first = backfill(db, apply=True)
        after_first = _trust(db, "inv-idem")

        second = backfill(db, apply=True)

        assert first["changed"] == 1
        assert second["changed"] == 0
        assert _trust(db, "inv-idem") == after_first

    def test_apply_emits_a_rollback_record_per_changed_row(self, db):
        _inv(db, "inv-rb", BLOCKQUOTE, trust={"verdict": None, "confidence": None})
        _inv(db, "inv-rb2", BLOCKQUOTE)
        buf = io.StringIO()

        backfill(db, apply=True, backup=buf)

        lines = [json.loads(line) for line in buf.getvalue().splitlines()]
        assert [line["job_id"] for line in lines] == ["inv-rb", "inv-rb2"]
        assert lines[0]["before"] == {"verdict": None, "confidence": None}
        assert lines[0]["after"]["verdict"] == "TRANSIENT"

    def test_limit_caps_rows_examined(self, db):
        for i in range(5):
            _inv(db, f"inv-l{i}", BLOCKQUOTE)

        report = backfill(db, apply=True, limit=2, batch_size=1)

        assert report["examined"] == 2
        assert report["changed"] == 2
