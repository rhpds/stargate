"""RED/GREEN TDD — Item 2: Ground truth dataset from real evaluations."""

from datetime import datetime, timezone

from db.models import EvaluationRecord, ProposedClassification


class TestGroundTruthBuilder:
    """Build a labeled dataset from approved proposals and confirmed evaluations."""

    def test_build_function_exists(self):
        from engine.ground_truth import build_ground_truth
        assert callable(build_ground_truth)

    def test_build_from_approved_proposals(self, db):
        """Approved ProposedClassifications become ground truth entries."""
        from engine.ground_truth import build_ground_truth

        db.add(ProposedClassification(
            run_id="run-1", stage_id="deployment-ready",
            proposed_class="pods_crashlooping", confidence=0.9,
            proposed_at=datetime.now(timezone.utc),
            reviewed=True, approved=True,
            reviewed_at=datetime.now(timezone.utc),
        ))
        db.add(ProposedClassification(
            run_id="run-2", stage_id="deployment-ready",
            proposed_class="pods_not_ready", confidence=0.8,
            proposed_at=datetime.now(timezone.utc),
            reviewed=True, approved=False,
        ))
        db.commit()

        gt = build_ground_truth(db)
        assert len(gt) == 1
        assert gt[0]["expected_class"] == "pods_crashlooping"
        assert gt[0]["source"] == "approved_proposal"

    def test_build_from_human_confirmed_evals(self, db):
        """Human-confirmed EvaluationRecords become ground truth entries."""
        from engine.ground_truth import build_ground_truth

        db.add(EvaluationRecord(
            run_id="run-1", stage_id="showroom-healthy",
            outcome="fail", failure_class="showroom_pod_down",
            evaluated_at=datetime.now(timezone.utc),
            human_confirmed=True,
        ))
        db.commit()

        gt = build_ground_truth(db)
        assert len(gt) >= 1
        confirmed = [e for e in gt if e["source"] == "human_confirmed"]
        assert len(confirmed) == 1
        assert confirmed[0]["expected_class"] == "showroom_pod_down"

    def test_ground_truth_has_required_fields(self, db):
        """Each ground truth entry must have expected_class, source, stage_id."""
        from engine.ground_truth import build_ground_truth

        db.add(ProposedClassification(
            run_id="run-1", stage_id="vm-runtime-ready",
            proposed_class="vmi_not_running", confidence=0.85,
            proposed_at=datetime.now(timezone.utc),
            reviewed=True, approved=True,
            reviewed_at=datetime.now(timezone.utc),
        ))
        db.commit()

        gt = build_ground_truth(db)
        assert len(gt) >= 1
        for entry in gt:
            assert "expected_class" in entry
            assert "source" in entry
            assert "stage_id" in entry
            assert "confirmed_at" in entry

    def test_measure_accuracy_function_exists(self):
        from engine.ground_truth import measure_accuracy
        assert callable(measure_accuracy)

    def test_measure_accuracy_returns_metrics(self, db):
        """measure_accuracy compares proposals against ground truth."""
        from engine.ground_truth import measure_accuracy

        db.add(ProposedClassification(
            run_id="run-1", stage_id="deployment-ready",
            proposed_class="pods_crashlooping", confidence=0.9,
            proposed_at=datetime.now(timezone.utc),
            reviewed=True, approved=True,
            reviewed_at=datetime.now(timezone.utc),
        ))
        db.add(ProposedClassification(
            run_id="run-2", stage_id="deployment-ready",
            proposed_class="pods_not_ready", confidence=0.7,
            proposed_at=datetime.now(timezone.utc),
            reviewed=True, approved=False,
            reviewed_at=datetime.now(timezone.utc),
        ))
        db.commit()

        result = measure_accuracy(db)
        assert "total" in result
        assert "correct" in result
        assert "accuracy" in result
        assert result["total"] == 2
        assert result["correct"] == 1
        assert result["accuracy"] == 0.5
