"""Lab detail must find evaluations recorded under other identities.

Live Nov 16 2026: `/dashboard/lab/ocp-field-asset-aws` reported "0 evaluations"
for a workload that had 200+ under `RHPDS agd-v2.ocp-field-asset-aws`. Each
collector names the same workload differently; the detail page queried only one
of those names.
"""

from datetime import datetime, timezone

from api.routers.dashboard.views import _evaluation_lab_codes
from db import repository
from db.models import EvaluationRecord

SLUG = "ocp-field-asset-aws"
AAP_TITLE = "RHPDS agd-v2.ocp-field-asset-aws"
SUBJECT = "agd-v2.ocp-field-asset-aws.prod-wxjcg-1"


def _add(db, lab_code, outcome="fail", failure_class="showroom_not_ready",
         stage="pods", cluster="ocpv06"):
    record = EvaluationRecord(
        run_id=f"run-{lab_code}-{outcome}-{stage}-{failure_class}",
        stage_id=stage,
        outcome=outcome,
        failure_class=failure_class,
        message="",
        criteria_results=[],
        evaluated_at=datetime.now(timezone.utc),
        lab_code=lab_code,
        cluster_name=cluster,
    )
    db.add(record)
    db.commit()
    return record


class TestAliasResolution:
    def test_resolves_aap_title_and_subject_names(self, db):
        _add(db, AAP_TITLE)
        _add(db, SUBJECT)

        aliases = _evaluation_lab_codes(db, SLUG)

        assert aliases[0] == SLUG
        assert AAP_TITLE in aliases
        assert SUBJECT in aliases

    def test_does_not_merge_a_different_workload(self, db):
        _add(db, "published.ocp-field-asset.prod")
        _add(db, "published.ocp-field-asset-cnv.prod")

        aliases = _evaluation_lab_codes(db, SLUG)

        assert aliases == [SLUG]

    def test_skips_namespace_shaped_identities(self, db):
        _add(db, "sandbox-abc12-ocp-field-asset-aws")
        _add(db, "guid:abc12")

        aliases = _evaluation_lab_codes(db, SLUG)

        assert aliases == [SLUG]

    def test_no_evaluations_returns_the_slug(self, db):
        assert _evaluation_lab_codes(db, SLUG) == [SLUG]


class TestRepositoryAggregation:
    def test_history_spans_all_aliases(self, db):
        _add(db, AAP_TITLE)
        _add(db, SUBJECT)
        aliases = _evaluation_lab_codes(db, SLUG)

        history = repository.get_evaluation_history(
            db, lab_code=SLUG, limit=50, lab_codes=aliases)

        assert len(history) == 2

    def test_history_without_aliases_stays_exact(self, db):
        _add(db, AAP_TITLE)

        history = repository.get_evaluation_history(db, lab_code=SLUG, limit=50)

        assert history == []

    def test_failure_frequency_spans_all_aliases(self, db):
        _add(db, AAP_TITLE, failure_class="showroom_not_ready")
        _add(db, SUBJECT, failure_class="pods_not_ready")
        aliases = _evaluation_lab_codes(db, SLUG)

        failures = repository.get_failure_class_frequency(
            db, lab_code=SLUG, lab_codes=aliases)

        assert failures == {"showroom_not_ready": 1, "pods_not_ready": 1}

    def test_last_passing_run_spans_all_aliases(self, db):
        _add(db, AAP_TITLE, outcome="pass", failure_class=None)
        aliases = _evaluation_lab_codes(db, SLUG)

        last_pass = repository.get_last_passing_run(
            db, lab_code=SLUG, lab_codes=aliases)

        assert last_pass is not None
        assert last_pass["run_id"].startswith("run-RHPDS")


class TestEvaluationCount:
    """'Total Evals' is a count, not the length of a capped history list."""

    def test_counts_all_identities_and_ignores_the_history_cap(self, db):
        for i in range(60):
            _add(db, AAP_TITLE, outcome="pass" if i % 2 else "fail",
                 failure_class=None if i % 2 else f"class-{i}", stage=f"s{i}")
        aliases = _evaluation_lab_codes(db, SLUG)

        total = repository.count_evaluations(db, lab_code=SLUG, lab_codes=aliases)
        history = repository.get_evaluation_history(
            db, lab_code=SLUG, limit=50, lab_codes=aliases)

        assert total == 60
        assert len(history) == 50

    def test_exact_count_without_aliases(self, db):
        _add(db, AAP_TITLE)

        assert repository.count_evaluations(db, lab_code=SLUG) == 0
        assert repository.count_evaluations(db, lab_code=AAP_TITLE) == 1
