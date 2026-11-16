"""Replication counter — only increases matter, and only beyond tolerance."""

import json

from scripts.credential_replication_check import diff_counts, main


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


class TestMain:
    def test_exit_code_and_json(self, tmp_path, monkeypatch, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"clusters": {"c1": _baseline(10)}}))
        monkeypatch.setattr(
            "scripts.credential_replication_check.count_live",
            lambda kubeconfig: {"abc123def4567890": 40},
        )

        code = main(["--cluster", "c1", "--kubeconfig", "/dev/null",
                     "--baseline", str(baseline), "--json"])

        assert code == 1
        out = json.loads(capsys.readouterr().out)
        assert out["cluster"] == "c1"
        assert out["drift"][0]["increase"] == 30

    def test_no_baseline_is_clean(self, tmp_path, monkeypatch):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"clusters": {}}))
        monkeypatch.setattr(
            "scripts.credential_replication_check.count_live",
            lambda kubeconfig: {},
        )

        assert main(["--cluster", "missing", "--kubeconfig", "/dev/null",
                     "--baseline", str(baseline)]) == 0
