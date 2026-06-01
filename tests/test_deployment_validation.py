"""EDD tests — Deployment validation: Containerfile, AgnosticV CI, Helm chart, env config."""

import os
import re
from pathlib import Path

import yaml
import pytest

PROJECT_DIR = Path(__file__).parent.parent


class TestContainerfile:

    def test_containerfile_exists(self):
        assert (PROJECT_DIR / "Containerfile").exists()

    def test_all_copy_sources_exist(self):
        cf = (PROJECT_DIR / "Containerfile").read_text()
        for line in cf.splitlines():
            if line.strip().startswith("COPY") and not line.strip().startswith("COPY --from"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    src = parts[1].rstrip("/")
                    if src in (".", "pyproject.toml"):
                        continue
                    src_path = PROJECT_DIR / src
                    assert src_path.exists(), f"COPY source missing: {src}"

    def test_exposes_port_8090(self):
        cf = (PROJECT_DIR / "Containerfile").read_text()
        assert "EXPOSE 8090" in cf

    def test_uses_ubi_base(self):
        cf = (PROJECT_DIR / "Containerfile").read_text()
        assert "registry.access.redhat.com/ubi9" in cf

    def test_installs_oc_cli(self):
        cf = (PROJECT_DIR / "Containerfile").read_text()
        assert "openshift-client" in cf or "oc kubectl" in cf


class TestAgnosticVCI:

    def test_ci_directory_exists(self):
        assert (PROJECT_DIR / "deploy" / "agnosticv" / "stargate-platform").is_dir()

    def test_common_yaml_exists(self):
        assert (PROJECT_DIR / "deploy" / "agnosticv" / "stargate-platform" / "common.yaml").exists()

    def test_stage_overrides_exist(self):
        ci_dir = PROJECT_DIR / "deploy" / "agnosticv" / "stargate-platform"
        assert (ci_dir / "dev.yaml").exists()
        assert (ci_dir / "integration.yaml").exists()
        assert (ci_dir / "prod.yaml").exists()

    def test_common_yaml_has_required_fields(self):
        ci = yaml.safe_load((PROJECT_DIR / "deploy" / "agnosticv" / "stargate-platform" / "common.yaml").read_text())
        assert "config" in ci
        assert "cloud_provider" in ci
        assert "__meta__" in ci
        meta = ci["__meta__"]
        assert "owners" in meta
        assert "catalog" in meta
        assert "deployer" in meta

    def test_meta_has_catalog_info(self):
        ci = yaml.safe_load((PROJECT_DIR / "deploy" / "agnosticv" / "stargate-platform" / "common.yaml").read_text())
        catalog = ci["__meta__"]["catalog"]
        assert "display_name" in catalog
        assert "category" in catalog
        assert "keywords" in catalog


class TestHelmChart:

    def test_chart_yaml_exists(self):
        assert (PROJECT_DIR / "deploy" / "helm" / "stargate" / "Chart.yaml").exists()

    def test_values_yaml_exists(self):
        assert (PROJECT_DIR / "deploy" / "helm" / "stargate" / "values.yaml").exists()

    def test_values_infra01_exists(self):
        assert (PROJECT_DIR / "deploy" / "helm" / "stargate" / "values-infra01.yaml").exists()

    def test_templates_exist(self):
        tmpl = PROJECT_DIR / "deploy" / "helm" / "stargate" / "templates"
        assert (tmpl / "api.yaml").exists()
        assert (tmpl / "postgres.yaml").exists()
        assert (tmpl / "routes.yaml").exists()
        assert (tmpl / "rbac.yaml").exists()

    def test_values_no_hardcoded_secrets(self):
        values = (PROJECT_DIR / "deploy" / "helm" / "stargate" / "values.yaml").read_text()
        assert "password: stargate" not in values
        assert "password: changeme" not in values


class TestAnsibleRole:

    def test_role_exists(self):
        assert (PROJECT_DIR / "deploy" / "ansible" / "roles" / "stargate_deploy").is_dir()

    def test_tasks_main_exists(self):
        assert (PROJECT_DIR / "deploy" / "ansible" / "roles" / "stargate_deploy" / "tasks" / "main.yaml").exists()

    def test_defaults_main_exists(self):
        assert (PROJECT_DIR / "deploy" / "ansible" / "roles" / "stargate_deploy" / "defaults" / "main.yaml").exists()

    def test_defaults_no_hardcoded_credentials(self):
        defaults = (PROJECT_DIR / "deploy" / "ansible" / "roles" / "stargate_deploy" / "defaults" / "main.yaml").read_text()
        # Ensure no real credential values are hardcoded (empty strings are OK)
        lines = [l.strip() for l in defaults.splitlines() if l.strip() and not l.strip().startswith("#")]
        for line in lines:
            if ":" in line:
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                assert len(val) < 50 or val == "", f"Suspiciously long value in defaults: {line[:60]}"


class TestDeployScripts:

    def test_deploy_script_exists(self):
        assert (PROJECT_DIR / "scripts" / "deploy.sh").exists()

    def test_deploy_script_executable(self):
        assert os.access(PROJECT_DIR / "scripts" / "deploy.sh", os.X_OK)

    def test_refresh_kubeconfigs_exists(self):
        assert (PROJECT_DIR / "scripts" / "refresh-kubeconfigs.sh").exists()

    def test_build_and_tag_exists(self):
        assert (PROJECT_DIR / "scripts" / "build-and-tag.sh").exists()
