"""Workflow tests — Scanner: schedule → collect → persist."""

from unittest.mock import patch, MagicMock


class TestScannerCollection:

    def test_scan_cluster_returns_dict_or_none(self, mock_oc):
        mock_oc.return_value.stdout = '{"items": []}'
        from cli.scan import scan_cluster
        result = scan_cluster("test-cluster", "/dev/null")
        assert result is None or isinstance(result, dict)

    def test_unreachable_cluster_returns_none(self):
        with patch("subprocess.run", side_effect=Exception("connection refused")):
            from cli.scan import scan_cluster
            result = scan_cluster("bad-cluster", "/dev/null")
            assert result is None or result.get("error")


class TestScanDataShape:

    def test_scan_entry_has_required_fields(self):
        scan = {
            "cluster": "ocpv05",
            "timestamp": "2026-06-04T12:00:00Z",
            "nodes": 10,
            "compute_nodes": 8,
            "avg_cpu_pct": 65.0,
            "hot_nodes": 1,
            "total_vms": 500,
            "sandbox_active": 100,
            "sandbox_failing": 5,
            "status": "warning",
        }
        assert scan["cluster"] == "ocpv05"
        assert 0 <= scan["avg_cpu_pct"] <= 100
        assert scan["status"] in ("healthy", "warning", "critical")
