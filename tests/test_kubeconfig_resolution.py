"""Kubeconfig resolution across canonical and pre-rotation filenames.

The 2026 Turkey Vulture rotation revoked the scanner tokens but left the old
filenames in code defaults (`kubeconfig-cnv` for ocpv06, `kubeconfig` for
ocp-us-east-1). A redeploy would have pointed the scanner at dead credentials,
so resolution now prefers `kubeconfig-<cluster>` and only falls back to the
legacy name while it still exists.
"""

from pathlib import Path

from cli.kubeconfigs import canonical_name, resolve_kubeconfig


def _touch(path: Path) -> Path:
    path.write_text("apiVersion: v1\n")
    return path


class TestCanonicalName:
    def test_uses_cluster_name(self):
        assert canonical_name("ocpv06") == "kubeconfig-ocpv06"
        assert canonical_name("ocp-us-east-1") == "kubeconfig-ocp-us-east-1"


class TestResolution:
    def test_prefers_canonical(self, tmp_path):
        _touch(tmp_path / "kubeconfig-ocpv06")
        _touch(tmp_path / "kubeconfig-cnv")

        resolved = resolve_kubeconfig("ocpv06", secrets_dir=tmp_path)

        assert resolved.name == "kubeconfig-ocpv06"

    def test_falls_back_to_legacy_alias(self, tmp_path):
        _touch(tmp_path / "kubeconfig-cnv")

        resolved = resolve_kubeconfig("ocpv06", secrets_dir=tmp_path)

        assert resolved.name == "kubeconfig-cnv"

    def test_returns_canonical_path_when_nothing_exists(self, tmp_path):
        resolved = resolve_kubeconfig("ocpv06", secrets_dir=tmp_path)

        # The error should name the file that should be there.
        assert resolved.name == "kubeconfig-ocpv06"

    def test_explicit_filename_wins(self, tmp_path):
        _touch(tmp_path / "kubeconfig-ocpv06")
        _touch(tmp_path / "custom-kc")

        resolved = resolve_kubeconfig("ocpv06", "custom-kc", secrets_dir=tmp_path)

        assert resolved.name == "custom-kc"

    def test_explicit_legacy_name_still_resolves(self, tmp_path):
        _touch(tmp_path / "kubeconfig-cnv")

        resolved = resolve_kubeconfig("ocpv06", "kubeconfig-cnv", secrets_dir=tmp_path)

        assert resolved.name == "kubeconfig-cnv"

    def test_east_1_legacy_name(self, tmp_path):
        _touch(tmp_path / "kubeconfig")

        resolved = resolve_kubeconfig("ocp-us-east-1", "kubeconfig", secrets_dir=tmp_path)

        assert resolved.name == "kubeconfig"


class TestDefaultClusters:
    def test_defaults_are_canonical(self, monkeypatch):
        monkeypatch.delenv("STARGATE_CLUSTERS", raising=False)
        monkeypatch.delenv("STARGATE_CLUSTERS_FILE", raising=False)
        from cli import scan

        clusters = scan.load_clusters()

        assert clusters["ocpv06"] == "kubeconfig-ocpv06"
        assert "kubeconfig-cnv" not in clusters.values()

    def test_env_names_map_to_canonical(self, monkeypatch):
        monkeypatch.setenv("STARGATE_CLUSTERS", "ocpv06,ocpv07")
        from cli import scan

        clusters = scan.load_clusters()

        assert clusters == {
            "ocpv06": "kubeconfig-ocpv06",
            "ocpv07": "kubeconfig-ocpv07",
        }
