"""Live lab inventory from recent evaluations."""

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def _eval(db, lab, cluster, stage, outcome, minutes, cls=None):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=f"r-{lab}-{stage}-{minutes}", stage_id=stage, outcome=outcome,
        failure_class=cls if outcome in ("fail", "warn") else None,
        lab_code=lab, cluster_name=cluster,
        evaluated_at=NOW - timedelta(minutes=minutes),
    ))
    db.commit()


class TestLiveLabs:
    def test_state_is_derived_per_stage(self, db):
        from db.repository import live_labs

        _eval(db, "sandbox-a-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 10)
        _eval(db, "sandbox-a-zt-rhelbu", "ocpv08", "deployment-ready", "fail", 5,
              "pods_not_ready")
        _eval(db, "sandbox-b-zt-rhelbu", "ocpv07", "namespace-ready", "pass", 8)
        _eval(db, "sandbox-b-zt-rhelbu", "ocpv07", "deployment-ready", "pass", 4)

        report = live_labs(db, window_hours=2)
        by_lab = {row["lab"]: row for row in report["labs"]}

        assert by_lab["sandbox-a-zt-rhelbu"]["state"] == "failing"
        assert by_lab["sandbox-a-zt-rhelbu"]["failure_class"] == "pods_not_ready"
        assert by_lab["sandbox-b-zt-rhelbu"]["state"] == "ready"
        assert report["summary"] == {
            **report["summary"],
            "labs": 2, "ready": 1, "failing": 1, "unknown": 0,
        }

    def test_owner_and_catalog_come_from_the_mapping(self, db):
        from db.models import LabMapping
        from db.repository import live_labs

        _eval(db, "sandbox-c-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 3)
        db.add(LabMapping(lab_code="sandbox-c-zt-rhelbu", owner="babylon",
                          ci_slug="zero-touch-base-rhel"))
        db.commit()

        row = live_labs(db, window_hours=2)["labs"][0]

        assert row["owner"] == "babylon"
        assert row["catalog_item"] == "zero-touch-base-rhel"
        assert row["family"] == "zt-rhelbu"

    def test_stale_labs_are_not_live(self, db):
        from db.repository import live_labs
        _eval(db, "sandbox-old-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 180)
        assert live_labs(db, window_hours=2)["summary"]["labs"] == 0


class TestWarnIsObservedNotUnknown:
    """`warn` is reached only after required-failure and unobserved are ruled out.

    engine/rubric_evaluator.py resolves required failure → indeterminate →
    warn → pass. So a lab whose only non-pass outcomes are `warn` passed every
    required criterion it was measured on. Calling it `unknown` claims we never
    measured it, which is exactly the thing we know is false. Measured against
    the live store: 172 warn rows in 2 h, none with a required criterion not
    observed True, none containing an unobserved criterion.
    """

    def test_pass_plus_warn_is_ready_and_flagged_degraded(self, db):
        from db.repository import live_labs

        _eval(db, "sandbox-g-ocp4-cluster", "ocpv06", "namespace-ready", "pass", 6)
        _eval(db, "sandbox-g-ocp4-cluster", "ocpv06", "vm-runtime-ready", "warn", 5,
              "guest_agent_not_connected")
        _eval(db, "sandbox-h-ocp4-cluster", "ocpv06", "namespace-ready", "pass", 6)
        _eval(db, "sandbox-h-ocp4-cluster", "ocpv06", "vm-runtime-ready", "pass", 5)

        report = live_labs(db, window_hours=2)
        by_lab = {row["lab"]: row for row in report["labs"]}

        assert by_lab["sandbox-g-ocp4-cluster"]["state"] == "ready"
        assert by_lab["sandbox-g-ocp4-cluster"]["degraded"] is True
        assert by_lab["sandbox-g-ocp4-cluster"]["warnings"] == [
            {"stage": "vm-runtime-ready", "failure_class": "guest_agent_not_connected"}
        ]
        assert by_lab["sandbox-h-ocp4-cluster"]["state"] == "ready"
        assert by_lab["sandbox-h-ocp4-cluster"]["degraded"] is False
        assert by_lab["sandbox-h-ocp4-cluster"]["warnings"] == []
        assert report["summary"]["ready"] == 2
        assert report["summary"]["degraded"] == 1
        assert report["summary"]["unknown"] == 0

    def test_warn_does_not_mask_a_failure_elsewhere(self, db):
        from db.repository import live_labs

        _eval(db, "sandbox-i-ocp4-cluster", "ocpv06", "vm-runtime-ready", "warn", 5)
        _eval(db, "sandbox-i-ocp4-cluster", "ocpv06", "deployment-ready", "fail", 4,
              "pods_not_ready")

        row = live_labs(db, window_hours=2)["labs"][0]

        assert row["state"] == "failing"
        assert row["failure_class"] == "pods_not_ready"
        assert row["degraded"] is False
        assert row["warnings"][0]["stage"] == "vm-runtime-ready"

    def test_indeterminate_stays_unknown(self, db):
        from db.repository import live_labs

        _eval(db, "sandbox-j-ocp4-cluster", "ocpv06", "namespace-ready", "pass", 6)
        _eval(db, "sandbox-j-ocp4-cluster", "ocpv06", "route-ready", "indeterminate", 5)

        row = live_labs(db, window_hours=2)["labs"][0]

        assert row["state"] == "unknown"
        assert row["degraded"] is False

    def test_retry_and_escalate_are_not_ready(self, db):
        """Stage-level markers are not a statement about readiness."""
        from db.repository import live_labs

        _eval(db, "sandbox-k-ocp4-cluster", "ocpv06", "namespace-ready", "pass", 6)
        _eval(db, "sandbox-k-ocp4-cluster", "ocpv06", "route-ready", "retry", 5)
        _eval(db, "sandbox-l-ocp4-cluster", "ocpv06", "namespace-ready", "pass", 6)
        _eval(db, "sandbox-l-ocp4-cluster", "ocpv06", "route-ready", "escalate", 5)

        by_lab = {row["lab"]: row["state"] for row in live_labs(db, window_hours=2)["labs"]}

        assert by_lab == {"sandbox-k-ocp4-cluster": "unknown", "sandbox-l-ocp4-cluster": "unknown"}

    def test_a_stale_warning_is_not_reported(self, db):
        """Only the latest outcome per stage counts — a warn since replaced by pass."""
        from db.repository import live_labs

        _eval(db, "sandbox-m-ocp4-cluster", "ocpv06", "vm-runtime-ready", "warn", 9)
        _eval(db, "sandbox-m-ocp4-cluster", "ocpv06", "vm-runtime-ready", "pass", 3)

        row = live_labs(db, window_hours=2)["labs"][0]

        assert row["state"] == "ready"
        assert row["degraded"] is False
        assert row["warnings"] == []


class TestSurfaces:
    def test_http_endpoint(self, client, db):
        _eval(db, "sandbox-d-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 3)
        body = client.get("/labs/live?window_hours=2").json()
        assert body["summary"]["ready"] == 1
        assert body["labs"][0]["lab"] == "sandbox-d-zt-rhelbu"

    def test_mcp_tool(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _eval(db, "sandbox-e-zt-rhelbu", "ocpv08", "deployment-ready", "fail", 2,
              "pods_not_ready")
        out = mcp_server.get_live_labs(window_hours=2)
        assert '"state": "failing"' in out


class TestOnlyRealLabs:
    def test_service_and_cluster_evaluations_are_excluded(self, db):
        from db.repository import live_labs

        _eval(db, "sandbox-f-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 2)
        _eval(db, "babylon", "", "cluster-health", "pass", 2)
        _eval(db, "primary", "", "model-endpoint-ready", "pass", 2)
        _eval(db, "jira", "", "dependency-health", "pass", 2)

        report = live_labs(db, window_hours=2)

        assert report["summary"]["labs"] == 1
        assert report["labs"][0]["lab"] == "sandbox-f-zt-rhelbu"
