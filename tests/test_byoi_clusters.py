"""RED/GREEN TDD — Phase 2: BYOI — Verify cluster list is environment-driven."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestClusterLoading:
    """Cluster list must be loadable from env vars, not just hardcoded Python."""

    def test_load_clusters_function_exists(self):
        from cli.scan import load_clusters
        assert callable(load_clusters)

    def test_fallback_to_default_clusters(self):
        """With no env vars set, returns the current 9-cluster dict."""
        from cli.scan import load_clusters
        with patch.dict(os.environ, {}, clear=False):
            for key in ("STARGATE_CLUSTERS", "STARGATE_CLUSTERS_FILE"):
                os.environ.pop(key, None)
            clusters = load_clusters()
        assert isinstance(clusters, dict)
        assert len(clusters) >= 9
        assert "ocpv05" in clusters

    def test_clusters_from_json_env_var(self):
        """STARGATE_CLUSTERS as JSON dict overrides the default."""
        from cli.scan import load_clusters
        custom = {"test-cluster-1": "kubeconfig-test1", "test-cluster-2": "kubeconfig-test2"}
        with patch.dict(os.environ, {"STARGATE_CLUSTERS": json.dumps(custom)}, clear=False):
            clusters = load_clusters()
        assert clusters == custom

    def test_clusters_csv_env_var(self):
        """STARGATE_CLUSTERS as comma-separated names → kubeconfig-{name} convention."""
        from cli.scan import load_clusters
        with patch.dict(os.environ, {"STARGATE_CLUSTERS": "alpha,beta,gamma"}, clear=False):
            clusters = load_clusters()
        assert clusters == {
            "alpha": "kubeconfig-alpha",
            "beta": "kubeconfig-beta",
            "gamma": "kubeconfig-gamma",
        }

    def test_clusters_from_yaml_file(self, tmp_path):
        """STARGATE_CLUSTERS_FILE env var loads clusters from a YAML file."""
        import yaml
        cluster_data = {"prod-1": "kubeconfig-prod1", "prod-2": "kubeconfig-prod2"}
        yaml_file = tmp_path / "clusters.yaml"
        yaml_file.write_text(yaml.dump(cluster_data))
        from cli.scan import load_clusters
        with patch.dict(os.environ, {"STARGATE_CLUSTERS_FILE": str(yaml_file)}, clear=False):
            os.environ.pop("STARGATE_CLUSTERS", None)
            clusters = load_clusters()
        assert clusters == cluster_data

    def test_module_level_clusters_alias(self):
        """CLUSTERS module-level variable remains available for backward compat."""
        from cli.scan import CLUSTERS
        assert isinstance(CLUSTERS, dict)
        assert len(CLUSTERS) > 0
