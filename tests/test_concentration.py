"""Concentration — the largest offenders, ranked with cumulative share.

TDD: written before engine/concentration.py exists. Pins:
- ranking with share and cumulative percentage
- the lab vs infra-namespace split (the top failure 'labs' are platform
  components — openshift-storage et al. — found live Nov 13 2026)
- catalog channel normalization (RHPDS x / x.prod / x.dev are one item)
- time-windowed, never unbounded
"""

from datetime import datetime, timedelta, timezone

from engine.concentration import (
    classify_lab_code,
    failure_concentration,
    provision_concentration,
)

NOW = datetime.now(timezone.utc)


def _seed_evals(db, lab, fails, days_ago=1):
    from db.models import EvaluationRecord
    for i in range(fails):
        db.add(EvaluationRecord(
            run_id="c-%s-%d" % (lab, i), stage_id="s", outcome="fail",
            evaluated_at=NOW - timedelta(days=days_ago), lab_code=lab))
    db.commit()


def _seed_source(db, item, jobs, days_ago=1):

    from db.models import SourceEvent
    for i in range(jobs):
        db.add(SourceEvent(
            source_system="aap", source_instance="prod0",
            source_event_id="j-%s-%d" % (item, i), outcome="success",
            evidence_hash="h-%s-%d" % (item, i),
            normalized_error="", catalog_item=item,
            first_seen_at=NOW - timedelta(days=days_ago),
            last_seen_at=NOW - timedelta(days=days_ago),
            occurred_at=NOW - timedelta(days=days_ago)))
    db.commit()


class TestClassify:
    def test_sandbox_is_lab(self):
        assert classify_lab_code("sandbox-lhlqc-zt-ansiblebu") == "lab"

    def test_infra_namespace_is_platform(self):
        assert classify_lab_code("openshift-storage") == "platform"
        assert classify_lab_code("default") == "platform"
        assert classify_lab_code("kube-system") == "platform"


class TestFailureConcentration:
    def test_ranking_share_and_cumulative(self, db):
        _seed_evals(db, "sandbox-a-lab1", 60)
        _seed_evals(db, "sandbox-a-lab2", 30)
        _seed_evals(db, "sandbox-a-lab3", 10)
        result = failure_concentration(db, days=7, limit=10)
        assert result["total_failures"] == 100
        top = result["entries"][0]
        assert top["lab_code"] == "sandbox-a-lab1"
        assert top["share_pct"] == 60.0
        assert result["entries"][0]["cumulative_pct"] == 60.0
        assert result["entries"][1]["cumulative_pct"] == 90.0

    def test_lab_vs_platform_split(self, db):
        _seed_evals(db, "openshift-storage", 500)
        _seed_evals(db, "sandbox-split-lab1", 5)
        result = failure_concentration(db, days=7, limit=10)
        # the platform namespace dominates the raw ranking...
        assert result["entries"][0]["lab_code"] == "openshift-storage"
        assert result["entries"][0]["kind"] == "platform"
        # ...but the labs-only view surfaces the actual lab
        assert result["labs_only"][0]["lab_code"] == "sandbox-split-lab1"
        assert result["split"]["platform_pct"] > result["split"]["lab_pct"]

    def test_window_excludes_old_failures(self, db):
        _seed_evals(db, "sandbox-a-lab1", 10, days_ago=1)
        _seed_evals(db, "sandbox-a-old-lab", 100, days_ago=60)
        result = failure_concentration(db, days=7, limit=10)
        assert result["total_failures"] == 10


class TestProvisionConcentration:
    def test_channel_normalization(self, db):
        _seed_source(db, "RHPDS agd-v2.ocp-cluster-cnv-pools", 40)
        _seed_source(db, "agd-v2.ocp-cluster-cnv-pools.prod", 30)
        _seed_source(db, "agd-v2.ocp-cluster-cnv-pools.dev", 30)
        _seed_source(db, "agd-v2.other-item.prod", 20)
        result = provision_concentration(db, days=7, limit=10)
        assert result["total_provisions"] == 120
        top = result["entries"][0]
        assert top["catalog_item"] == "agd-v2.ocp-cluster-cnv-pools"
        assert top["jobs"] == 100
        assert top["share_pct"] == round(100.0 * 100 / 120, 2)

    def test_ranking_and_cumulative(self, db):
        _seed_source(db, "item-a.prod", 50)
        _seed_source(db, "item-b.prod", 50)
        result = provision_concentration(db, days=7, limit=10)
        assert result["entries"][0]["cumulative_pct"] == 50.0
        assert result["entries"][1]["cumulative_pct"] == 100.0
