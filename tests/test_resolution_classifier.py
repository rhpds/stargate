"""Unit tests for engine/resolution_classifier.py — resolution profile classification."""

import json
from unittest.mock import patch

import pytest


def _shadow_state(entries):
    """Build a shadow-state dict with the given entries as shadow_log."""
    return {"shadow_log": entries, "incident_log": []}


def _entry(fc="readiness_probe_failed", catalog_item="ocp4-cluster", resolved=True,
           cause="self_resolved", detected_at="2026-08-20T10:00:00Z",
           resolved_at="2026-08-20T10:05:00Z"):
    e = {"failure_class": fc, "catalog_item": catalog_item, "resolved": resolved}
    if resolved and cause:
        e["resolution_cause"] = {"cause": cause}
    if detected_at:
        e["detected_at"] = detected_at
    if resolved and resolved_at:
        e["resolved_at"] = resolved_at
    return e


def _run(state):
    """Run build_resolution_profiles against a mocked shadow-state file."""
    from pathlib import Path
    from unittest.mock import MagicMock

    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = json.dumps(state)

    with patch("engine.resolution_classifier.SHADOW_STATE_FILE", mock_path):
        from engine.resolution_classifier import build_resolution_profiles
        return build_resolution_profiles()


class TestNoData:
    def test_missing_file_returns_no_data(self):
        from pathlib import Path
        from unittest.mock import MagicMock

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False

        with patch("engine.resolution_classifier.SHADOW_STATE_FILE", mock_path):
            from engine.resolution_classifier import build_resolution_profiles
            result = build_resolution_profiles()

        assert result["status"] == "no_data"
        assert result["profiles"] == {}

    def test_empty_logs(self):
        result = _run({"shadow_log": [], "incident_log": []})
        assert result["status"] == "ok"
        assert result["total_profiles"] == 0


class TestSandboxPrefixStripping:
    def test_strips_sandbox_prefix(self):
        entries = [_entry(catalog_item="sandbox-ab12c-ocp4-cluster") for _ in range(10)]
        result = _run(_shadow_state(entries))
        key = "ocp4-cluster:readiness_probe_failed"
        assert key in result["profiles"]
        assert result["profiles"][key]["catalog_item"] == "ocp4-cluster"

    def test_non_sandbox_unchanged(self):
        entries = [_entry(catalog_item="my-custom-lab") for _ in range(10)]
        result = _run(_shadow_state(entries))
        key = "my-custom-lab:readiness_probe_failed"
        assert key in result["profiles"]


class TestWatchAndWait:
    def test_high_self_resolve_rate(self):
        entries = [_entry(cause="self_resolved") for _ in range(10)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "watch_and_wait"
        assert profile["sufficient_data"] is True
        assert profile["self_resolve_rate"] == 1.0

    def test_high_namespace_recycled_rate(self):
        entries = [_entry(cause="namespace_recycled") for _ in range(10)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "watch_and_wait"
        assert "namespace lifecycle" in profile["reasoning"]

    def test_majority_self_resolve(self):
        entries = [_entry(cause="self_resolved") for _ in range(7)]
        entries += [_entry(cause="human_remediated") for _ in range(3)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "watch_and_wait"


class TestInvestigate:
    def test_high_human_intervention(self):
        entries = [_entry(cause="human_remediated") for _ in range(5)]
        entries += [_entry(cause="self_resolved") for _ in range(5)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "investigate"
        assert "human intervention" in profile["reasoning"]

    def test_more_unresolved_than_resolved(self):
        entries = [_entry(resolved=True, cause="other_fix") for _ in range(4)]
        entries += [_entry(resolved=False) for _ in range(8)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "investigate"
        assert "unresolved" in profile["reasoning"].lower()

    def test_sufficient_data_zero_resolved(self):
        entries = [_entry(resolved=False) for _ in range(12)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "investigate"
        assert "0 resolved" in profile["reasoning"]


class TestCandidateForAutoRemediation:
    def test_consistent_resolution_low_self_resolve(self):
        entries = [_entry(cause="auto_restart") for _ in range(10)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "candidate_for_auto_remediation"
        assert "candidate for automation" in profile["reasoning"]

    def test_mixed_causes_no_dominant(self):
        entries = [_entry(cause="auto_restart") for _ in range(4)]
        entries += [_entry(cause="config_fix") for _ in range(4)]
        entries += [_entry(cause="other") for _ in range(3)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["recommendation"] == "candidate_for_auto_remediation"


class TestInsufficientData:
    def test_below_min_resolutions(self):
        entries = [_entry() for _ in range(5)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["sufficient_data"] is False
        assert profile["recommendation"] is None

    def test_exactly_at_threshold(self):
        entries = [_entry(cause="self_resolved") for _ in range(10)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["sufficient_data"] is True
        assert profile["recommendation"] is not None


class TestTimeToResolve:
    def test_avg_time_computed(self):
        entries = [_entry(detected_at="2026-08-20T10:00:00Z",
                          resolved_at="2026-08-20T10:10:00Z") for _ in range(10)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["avg_time_to_resolve_minutes"] == 10.0

    def test_no_timestamps_returns_none(self):
        entries = [_entry(detected_at=None, resolved_at=None) for _ in range(10)]
        result = _run(_shadow_state(entries))
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["avg_time_to_resolve_minutes"] is None


class TestMultipleProfiles:
    def test_separate_profiles_per_class(self):
        entries = [_entry(fc="readiness_probe_failed") for _ in range(10)]
        entries += [_entry(fc="quota_exceeded", cause="human_remediated") for _ in range(10)]
        result = _run(_shadow_state(entries))
        assert result["total_profiles"] == 2
        assert "ocp4-cluster:readiness_probe_failed" in result["profiles"]
        assert "ocp4-cluster:quota_exceeded" in result["profiles"]

    def test_separate_profiles_per_catalog_item(self):
        entries = [_entry(catalog_item="ocp4-cluster") for _ in range(10)]
        entries += [_entry(catalog_item="zt-ansiblebu") for _ in range(10)]
        result = _run(_shadow_state(entries))
        assert result["total_profiles"] == 2

    def test_sufficient_data_count(self):
        entries = [_entry(fc="a") for _ in range(10)]
        entries += [_entry(fc="b") for _ in range(3)]
        result = _run(_shadow_state(entries))
        assert result["sufficient_data_count"] == 1


class TestIncidentLogMerge:
    def test_incident_log_combined(self):
        state = {
            "shadow_log": [_entry() for _ in range(5)],
            "incident_log": [_entry() for _ in range(5)],
        }
        result = _run(state)
        profile = result["profiles"]["ocp4-cluster:readiness_probe_failed"]
        assert profile["total_observations"] == 10
        assert profile["sufficient_data"] is True
