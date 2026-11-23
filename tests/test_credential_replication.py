"""Replication counter — only increases matter, and only beyond tolerance."""

import json

from scripts.credential_replication_check import diff_counts, main, report


def _baseline(count: int, label: str = "fvmw-password"):
    return {"abc123def4567890": {"count": count, "label": label}}


class TestDiff:
    def test_increase_beyond_tolerance_is_drift(self):
        drift = diff_counts(_baseline(900), {"abc123def4567890": 951}, tolerance=5)

        assert len(drift) == 1
        assert drift[0]["increase"] == 51
        assert drift[0]["credential"] == "fvmw-password"

    def test_small_churn_is_ignored(self):
        assert diff_counts(_baseline(900), {"abc123def4567890": 903}, tolerance=5) == []

    def test_decrease_is_not_drift(self):
        assert diff_counts(_baseline(900), {"abc123def4567890": 10}, tolerance=5) == []

    def test_missing_credential_is_not_drift(self):
        assert diff_counts(_baseline(900), {}, tolerance=5) == []

    def test_unknown_hash_is_ignored(self):
        # a hash that is not in the baseline cannot be classified
        assert diff_counts(_baseline(0), {"ffffffffffffffff": 40}, tolerance=5) == []


class TestReport:
    """Drift belongs to the cluster it was measured on, not to the credential."""

    def _capture(self, monkeypatch):
        posted = []

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            posted.append(json.loads(request.data.decode()))
            return _Response()

        monkeypatch.setattr(
            "scripts.credential_replication_check.urllib.request.urlopen", fake_urlopen
        )
        return posted

    def test_cluster_name_is_the_cluster_not_the_credential(self, monkeypatch):
        posted = self._capture(monkeypatch)
        drift = diff_counts(_baseline(900), {"abc123def4567890": 951}, tolerance=5)

        assert report(drift, "http://api:8090", "key", "ocpv-infra01") == 1

        payload = posted[0]
        assert payload["cluster_name"] == "ocpv-infra01"
        # the old value was "replication:<sha256>", which no cluster filter matches
        assert not any(
            str(value).startswith("replication:") for value in payload.values()
        )

    def test_credential_is_still_named(self, monkeypatch):
        posted = self._capture(monkeypatch)
        drift = diff_counts(_baseline(900), {"abc123def4567890": 951}, tolerance=5)

        report(drift, "http://api:8090", "key", "ocpv-infra01")

        summary = posted[0]["error_summary"]
        assert "fvmw-password" in summary
        assert "abc123def4567890" in summary


class TestMain:
    def test_exit_code_and_json(self, tmp_path, monkeypatch, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"clusters": {"c1": _baseline(10)}}))
        monkeypatch.setattr(
            "scripts.credential_replication_check.count_live",
            lambda kubeconfig: {"abc123def4567890": 40},
        )

        code = main(["--cluster", "c1", "--kubeconfig", "/dev/null",
                     "--baseline", str(baseline), "--json", "--fail-on-drift"])

        assert code == 1
        out = json.loads(capsys.readouterr().out)
        assert out["cluster"] == "c1"
        assert out["drift"][0]["increase"] == 30

    def test_drift_reports_without_failing_by_default(self, tmp_path, monkeypatch, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"clusters": {"c1": _baseline(10)}}))
        monkeypatch.setattr(
            "scripts.credential_replication_check.count_live",
            lambda kubeconfig: {"abc123def4567890": 40},
        )

        code = main(["--cluster", "c1", "--kubeconfig", "/dev/null",
                     "--baseline", str(baseline), "--json"])

        assert code == 0
        assert json.loads(capsys.readouterr().out)["drift"]

    def test_no_baseline_is_clean(self, tmp_path, monkeypatch):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"clusters": {}}))
        monkeypatch.setattr(
            "scripts.credential_replication_check.count_live",
            lambda kubeconfig: {},
        )

        assert main(["--cluster", "missing", "--kubeconfig", "/dev/null",
                     "--baseline", str(baseline)]) == 0
