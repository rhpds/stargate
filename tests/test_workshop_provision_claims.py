"""Tests for the WorkshopProvision stall detector's claim-count semantics.

Found live Nov 16 2026: the RHDP control-plane WorkshopProvision controller
writes NO conditions and NO observedGeneration — its status carries
resourceClaimCount/failedCount/activeCount. The detector's conditions-based
stall check (`not ready and age >= 1h`) therefore flagged EVERY provision
older than an hour: 176/179 findings, 120 of them healthy with successful
claims. The fix: claim-count fallback semantics when conditions are absent.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


def _wp(name="wp-test", created_hours_ago=10, conditions=None,
        resource_claims=0, failed_count=0, active_count=0, generation=3):
    return {
        "metadata": {
            "name": name,
            "namespace": "user-x-redhat-com",
            "generation": generation,
            "creationTimestamp": (
                datetime.now(timezone.utc) - timedelta(hours=created_hours_ago)
            ).isoformat(),
        },
        "spec": {"catalogItem": "test-item"},
        "status": {
            "resourceClaimCount": resource_claims,
            "failedCount": failed_count,
            "activeCount": active_count,
        },
    }


def _run(items):
    """Run the detector's classification over the given items."""
    from cli import babylon_worker as bw
    findings = []
    succeeded = []
    for item in items:
        # replicate the per-item loop contract by calling the real function
        # through a patched _oc_json_with_status returning our items
        pass
    return findings, succeeded


class TestClaimCountSemantics:
    def _collect(self, items, monkeypatch):
        from cli import babylon_worker as bw

        def fake_oc(args, timeout=60):
            return {"items": items}, {"ok": True}

        monkeypatch.setattr(bw, "_oc_json_with_status", fake_oc)
        monkeypatch.setenv("STARGATE_WORKSHOP_PROVISION_NAMESPACES", "-A")
        return bw.collect_workshop_provisions()

    def test_healthy_claims_not_stalled(self, monkeypatch):
        """The regression: healthy provisions with successful claims were
        flagged stalled because they carry no 'ready' condition."""
        result = self._collect([_wp(resource_claims=5, active_count=4)], monkeypatch)
        assert result["finding_count"] == 0
        assert result["state_counts"].get("ready") == 1

    def test_failed_count_is_failure(self, monkeypatch):
        result = self._collect([_wp(resource_claims=2, failed_count=1)], monkeypatch)
        assert result["finding_count"] == 1
        assert result["findings"][0]["failure_class"] == "workshop_provision_failed"
        assert result["state_counts"].get("failed") == 1

    def test_dead_empty_claims_are_stalled(self, monkeypatch):
        """Zero claims after the threshold — the genuinely dead ones (the
        fleet has 39-day-old empties)."""
        result = self._collect([_wp(created_hours_ago=940)], monkeypatch)
        assert result["finding_count"] == 1
        assert result["findings"][0]["failure_class"] == "workshop_provision_stalled"

    def test_fresh_empty_claims_are_queue_not_stall(self, monkeypatch):
        """Zero claims under the threshold — the normal provisioning queue
        (the fleet's 1-7h empties)."""
        result = self._collect([_wp(created_hours_ago=2)], monkeypatch)
        assert result["finding_count"] == 0
        assert result["state_counts"].get("pending") == 1

    def test_conditions_stay_authoritative(self, monkeypatch):
        """A controller that DOES write conditions keeps the old semantics."""
        wp = _wp(resource_claims=5, active_count=5)
        wp["status"]["conditions"] = [{
            "type": "Ready", "status": "True",
            "lastTransitionTime": datetime.now(timezone.utc).isoformat(),
        }]
        result = self._collect([wp], monkeypatch)
        assert result["finding_count"] == 0
        assert result["state_counts"].get("ready") == 1

    def test_default_threshold_is_six_hours(self, monkeypatch):
        """The old 1h default was calibrated for conditions; with claim
        semantics the queue legitimately takes hours."""
        from cli import babylon_worker as bw
        result = self._collect([_wp(created_hours_ago=3)], monkeypatch)
        assert result["stall_threshold_hours"] == 6
        assert result["finding_count"] == 0

    def test_fleet_shape_live_data(self, monkeypatch):
        """The observed fleet: 120 healthy, 25 failed, old-empties stalled,
        fresh-empties pending — findings only for the real problems."""
        items = (
            [_wp(name=f"healthy-{i}", resource_claims=5, active_count=4) for i in range(120)]
            + [_wp(name=f"failed-{i}", resource_claims=2, failed_count=1) for i in range(25)]
            + [_wp(name=f"dead-{i}", created_hours_ago=940) for i in range(30)]
            + [_wp(name=f"queued-{i}", created_hours_ago=2) for i in range(23)]
        )
        result = self._collect(items, monkeypatch)
        # 25 failures + 30 dead — NOT the 176 the old logic produced
        assert result["finding_count"] == 55
        assert result["state_counts"] == {"ready": 120, "failed": 25, "pending": 53}
