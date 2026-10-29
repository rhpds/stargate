"""Tests for the stuck-teardown detector (collectors/cleanup/collect_stuck_teardowns.py).

Pins the cross-cluster namespace-existence fix: existence must be observed
on the subject's TARGET cluster (via its per-cluster kubeconfig), and
unobservable entries are None (unobserved), never a false negative from
querying the wrong cluster.
"""

import importlib
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import collectors.cleanup.collect_stuck_teardowns as collector


def _subject(name, state, age_hours, namespace="lab-ns", cluster="ocpv05"):
    transition = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z")
    return {
        "metadata": {"name": name, "creationTimestamp": transition},
        "status": {"state": state, "lastTransitionTime": transition},
        "spec": {"vars": {"job_vars": {"namespace": namespace, "cluster_name": cluster}}},
    }


class TestDetectStuckTeardowns:
    def test_finds_stuck_destroying_subjects(self, tmp_path):
        payload = {"items": [
            _subject("subj-stuck", "destroying", 3),
            _subject("subj-fine", "started", 10),
            _subject("subj-fresh", "destroying", 0.5),
        ]}
        kc = tmp_path / "kubeconfig-executor"
        kc.write_text("{}")
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(payload)
            result = collector.detect_stuck_teardowns(kubeconfig=str(kc))
        assert result["stuck_count"] == 1
        stuck = result["stuck"][0]
        assert stuck["anarchy_subject"] == "subj-stuck"
        assert stuck["state"] == "destroying"
        assert stuck["age_hours"] >= 3
        assert stuck["cluster"] == "ocpv05"

    def test_destroy_failed_and_error_states_count(self, tmp_path):
        payload = {"items": [
            _subject("a", "destroy-failed", 5),
            _subject("b", "destroy-error", 5),
        ]}
        kc = tmp_path / "kubeconfig-executor"
        kc.write_text("{}")
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(payload)
            result = collector.detect_stuck_teardowns(kubeconfig=str(kc))
        assert result["stuck_count"] == 2

    def test_collection_failure_reports_error(self, tmp_path):
        kc = tmp_path / "kubeconfig-executor"
        kc.write_text("{}")
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "not found"
            result = collector.detect_stuck_teardowns(kubeconfig=str(kc))
        assert result == {"error": "not found", "stuck": []}

    def test_threshold_is_env_configurable(self):
        original = collector.STUCK_THRESHOLD_HOURS
        try:
            with patch.dict(os.environ, {"STARGATE_STUCK_TEARDOWN_HOURS": "48"}):
                reloaded = importlib.reload(collector)
                assert reloaded.STUCK_THRESHOLD_HOURS == 48.0
        finally:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("STARGATE_STUCK_TEARDOWN_HOURS", None)
                importlib.reload(collector)
            assert collector.STUCK_THRESHOLD_HOURS == original


class TestNamespaceExistence:
    def _entry(self, cluster, namespace="lab-ns"):
        return {"anarchy_subject": "s", "namespace": namespace, "cluster": cluster}

    def _base_kubeconfig(self, tmp_path, clusters=()):
        base = tmp_path / "kubeconfig-executor"
        base.write_text("{}")
        for c in clusters:
            (tmp_path / f"kubeconfig-{c}").write_text("{}")
        return str(base)

    def test_queries_the_target_clusters_kubeconfig(self, tmp_path):
        base = self._base_kubeconfig(tmp_path, clusters=("ocpv05", "ocpv07"))
        entry = self._entry("ocpv05")
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "default lab-ns kube-system"
            collector._check_namespace_existence([entry], {"KUBECONFIG": base}, base)
        assert entry["namespace_exists"] is True
        used_kc = run.call_args.kwargs["env"]["KUBECONFIG"]
        assert used_kc.endswith("kubeconfig-ocpv05"), "must query the target cluster, not the base kubeconfig"

    def test_missing_namespace_observed_false_on_correct_cluster(self, tmp_path):
        base = self._base_kubeconfig(tmp_path, clusters=("ocpv05",))
        entry = self._entry("ocpv05")
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "default kube-system"
            collector._check_namespace_existence([entry], {}, base)
        assert entry["namespace_exists"] is False

    def test_unresolvable_cluster_is_unobserved_not_false(self, tmp_path):
        base = self._base_kubeconfig(tmp_path, clusters=("ocpv05",))
        entry = self._entry("ocpv99")  # no kubeconfig-ocpv99 exists
        with patch.object(collector.subprocess, "run") as run:
            collector._check_namespace_existence([entry], {}, base)
        assert entry["namespace_exists"] is None
        run.assert_not_called()

    def test_failed_query_is_unobserved_not_false(self, tmp_path):
        base = self._base_kubeconfig(tmp_path, clusters=("ocpv05",))
        entry = self._entry("ocpv05")
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "forbidden"
            collector._check_namespace_existence([entry], {}, base)
        assert entry["namespace_exists"] is None

    def test_unknown_cluster_label_is_unobserved(self, tmp_path):
        base = self._base_kubeconfig(tmp_path)
        entry = self._entry("unknown")
        collector._check_namespace_existence([entry], {}, base)
        assert entry["namespace_exists"] is None

    def test_entries_share_one_query_per_cluster(self, tmp_path):
        base = self._base_kubeconfig(tmp_path, clusters=("ocpv05", "ocpv07"))
        entries = [self._entry("ocpv05", namespace=f"ns-{i}") for i in range(3)]
        with patch.object(collector.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "ns-0 ns-1 ns-2"
            collector._check_namespace_existence(entries, {}, base)
        assert run.call_count == 1  # cached per cluster
        assert [e["namespace_exists"] for e in entries] == [True, True, True]
