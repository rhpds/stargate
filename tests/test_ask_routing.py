"""`ask` must fetch the new fleet numbers instead of guessing from docs."""

from datetime import datetime, timezone

from db.models import EvaluationRecord
from engine.stargate_qa import _structured_context


def _seed(db):
    db.add(EvaluationRecord(
        run_id="r1", stage_id="deployment-ready", outcome="fail",
        failure_class="pods_not_ready", lab_code="sandbox-abc12-zt-rhelbu",
        cluster_name="ocpv08", evaluated_at=datetime.now(timezone.utc),
    ))
    db.commit()


class TestAskRouting:
    def test_precision_question_gets_live_numbers(self, db):
        _seed(db)
        contexts = _structured_context("which failure classes are noisy?")
        assert any(c.startswith("[failure precision]") for c in contexts)

    def test_recovery_question_gets_durations(self, db):
        _seed(db)
        contexts = _structured_context("how long does recovery take?")
        assert any(c.startswith("[recovery time]") for c in contexts)

    def test_namespace_question_gets_the_session(self, db):
        _seed(db)
        contexts = _structured_context("what happened in sandbox-abc12-zt-rhelbu?")
        assert any(c.startswith("[lab session for sandbox-abc12-zt-rhelbu]") for c in contexts)
