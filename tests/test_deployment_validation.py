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

    def test_api_cpu_limit_clears_the_throttle(self):
        """A one-core API limit throttled 18.5% and 14.2% of CFS periods.

        Both replicas averaged 0.70 cores while every cluster's evidence
        uploads arrived at the same API, and the slow tail of `/evaluate` is
        requests waiting behind them. The chart is what a `helm upgrade`
        applies, so it has to agree with the running deployment or the next
        apply quietly puts the limit back.
        """
        values = yaml.safe_load(
            (PROJECT_DIR / "deploy" / "helm" / "stargate" / "values.yaml").read_text()
        )
        cpu = str(values["api"]["resources"]["limits"]["cpu"])
        cores = float(cpu[:-1]) / 1000 if cpu.endswith("m") else float(cpu)
        assert cores >= 2, f"api limits.cpu is {cpu}; one core throttled the evidence upload"


class TestHelmMonitoring:
    """StarGate served 356 `stargate_*` metric lines to nobody until 2026-11-23.

    No ServiceMonitor existed anywhere on the cluster, and the Service had no
    label one could have selected. These pin the four things that have to stay
    true together, none of which fails loudly on its own: the resources are
    gated, the Service carries the label the monitor selects, the monitor reads
    the container port rather than the oauth proxy, and the thresholds quoted in
    the runbook are the ones in the values.
    """

    TEMPLATES = PROJECT_DIR / "deploy" / "helm" / "stargate" / "templates"

    def _values(self, name: str) -> dict:
        return yaml.safe_load((PROJECT_DIR / "deploy" / "helm" / "stargate" / name).read_text())

    def test_off_by_default_and_on_for_infra01(self):
        # A ServiceMonitor on a cluster without the Prometheus Operator CRDs
        # fails the entire install, so the default has to be off.
        assert self._values("values.yaml")["monitoring"]["enabled"] is False
        assert self._values("values-infra01.yaml")["monitoring"]["enabled"] is True

    def test_templates_are_gated_on_that_value(self):
        template = (self.TEMPLATES / "monitoring.yaml").read_text()
        assert "{{- if .Values.monitoring.enabled }}" in template
        assert template.rstrip().endswith("{{- end }}")

    def test_servicemonitor_selects_a_label_the_service_carries(self):
        import re
        monitoring = (self.TEMPLATES / "monitoring.yaml").read_text()
        api = (self.TEMPLATES / "api.yaml").read_text()
        selected = re.search(r"matchLabels:\n\s+app: (\S+)", monitoring).group(1)
        service = api[api.index("kind: Service"):]
        # The label must be on the Service, not only on the pod template: a
        # ServiceMonitor selects Services.
        assert f"labels:\n    app: {selected}" in service

    def test_scrapes_the_container_port_not_the_oauth_proxy(self):
        monitoring = (self.TEMPLATES / "monitoring.yaml").read_text()
        assert "- port: api" in monitoring
        assert "port: proxy" not in monitoring, (
            "/metrics is auth-exempt; scraping it through the proxy would make "
            "an auth regression look like a monitoring outage"
        )

    def test_alert_thresholds_match_the_values_and_the_runbook(self):
        monitoring = (self.TEMPLATES / "monitoring.yaml").read_text()
        values = self._values("values.yaml")["monitoring"]
        runbook = (PROJECT_DIR / "docs" / "runbook.md").read_text()
        stale = values["tier3StaleSeconds"]
        never = values["tier3NeverScannedThreshold"]
        assert "{{ .Values.monitoring.tier3StaleSeconds }}" in monitoring
        assert f"{{{{ .Values.monitoring.tier3NeverScannedThreshold }}}}" in monitoring
        assert f"> {stale}`" in runbook
        assert f"> {never}`" in runbook

    def test_every_alert_is_documented(self):
        import re
        monitoring = (self.TEMPLATES / "monitoring.yaml").read_text()
        runbook = (PROJECT_DIR / "docs" / "runbook.md").read_text()
        alerts = re.findall(r"- alert: (\w+)", monitoring)
        assert alerts, "no alerts found — the rule file or its indentation changed"
        missing = [a for a in alerts if f"`{a}`" not in runbook]
        assert missing == [], f"alerts with no runbook entry: {missing}"


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
                key = line.split(":", 1)[0].strip()
                if key.endswith("_image"):
                    continue
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
