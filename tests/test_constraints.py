"""Stage 3 — AgnosticV constraint classification tests."""

from pathlib import Path

import pytest

from constraints.agnosticv_loader import load_lab_constraints, load_all_constraints
from constraints.classifier import classify_constraints, ConstraintViolation

AGNOSTICV_DIR = Path(__file__).parent.parent.parent / "github review" / "agnosticv"
SUMMIT_DIR = AGNOSTICV_DIR / "summit-2026"


class TestAgnosticVLoader:
    @pytest.mark.skipif(not SUMMIT_DIR.exists(), reason="AgnosticV repo not cloned")
    def test_load_lb1088(self):
        constraints = load_lab_constraints(
            SUMMIT_DIR / "lb1088-code-red-breach-challenge-cnv" / "common.yaml"
        )
        assert "workloads" in constraints
        assert constraints["workload_count"] == 18
        assert constraints["ocp_version"] == "4.20"
        assert constraints["display_name"] == "LB1088: Code Red: The Breach Challenge!"
        assert constraints["timeout_seconds"] == 21600
        assert "collections" in constraints
        assert len(constraints["collections"]) > 5

    @pytest.mark.skipif(not SUMMIT_DIR.exists(), reason="AgnosticV repo not cloned")
    def test_load_lb1237(self):
        constraints = load_lab_constraints(
            SUMMIT_DIR / "lb1237-hol-rhel10-cnv" / "common.yaml"
        )
        assert constraints["cloud_provider"] == "openshift_cnv"
        assert constraints["config"] == "cloud-vms-base"

    @pytest.mark.skipif(not SUMMIT_DIR.exists(), reason="AgnosticV repo not cloned")
    def test_load_all_summit(self):
        labs = load_all_constraints(AGNOSTICV_DIR)
        assert len(labs) > 30
        # Verify no errors in most labs
        errors = {k: v for k, v in labs.items() if "error" in v}
        assert len(errors) < len(labs) / 2

    @pytest.mark.skipif(not SUMMIT_DIR.exists(), reason="AgnosticV repo not cloned")
    def test_operator_channels_extracted(self):
        constraints = load_lab_constraints(
            SUMMIT_DIR / "lb1088-code-red-breach-challenge-cnv" / "common.yaml"
        )
        channels = constraints.get("operator_channels", {})
        assert "rhacs_install_operator" in channels or "openshift_gitops" in channels

    @pytest.mark.skipif(not SUMMIT_DIR.exists(), reason="AgnosticV repo not cloned")
    def test_components_extracted(self):
        constraints = load_lab_constraints(
            SUMMIT_DIR / "lb1088-code-red-breach-challenge-cnv" / "common.yaml"
        )
        components = constraints.get("components", [])
        assert len(components) > 0
        assert components[0].get("item")


class TestConstraintClassifier:
    def test_missing_workload_detected(self):
        constraints = {
            "workloads": [
                "agnosticd.core_workloads.ocp4_workload_rhacs",
                "agnosticd.core_workloads.ocp4_workload_gitea_operator",
                "agnosticd.showroom.ocp4_workload_showroom",
            ],
        }
        evidence = {
            "pod_names": ["showroom-abc123", "gitea-operator-xyz789"],
            "deployment_names": ["showroom", "gitea-operator"],
            "deployed_namespaces": ["showroom", "gitea"],
            "deployed_operators": [],
        }

        violations = classify_constraints(constraints, evidence)
        workload_violations = [v for v in violations if v.violation_type == "workload_not_deployed"]
        assert len(workload_violations) == 1
        assert "rhacs" in workload_violations[0].expected

    def test_no_violations_when_all_deployed(self):
        constraints = {
            "workloads": [
                "agnosticd.showroom.ocp4_workload_showroom",
            ],
        }
        evidence = {
            "pod_names": ["showroom-pod-1"],
            "deployment_names": ["showroom"],
            "deployed_namespaces": ["showroom"],
            "deployed_operators": [],
        }
        violations = classify_constraints(constraints, evidence)
        workload_violations = [v for v in violations if v.violation_type == "workload_not_deployed"]
        assert len(workload_violations) == 0

    def test_operator_drift_detected(self):
        constraints = {
            "operator_channels": {"rhacs": "rhacs-4.9"},
        }
        evidence = {
            "operator_channels": {"rhacs": "rhacs-4.7"},
        }
        violations = classify_constraints(constraints, evidence)
        drift = [v for v in violations if v.violation_type == "operator_version_drift"]
        assert len(drift) == 1
        assert "4.9" in drift[0].expected
        assert "4.7" in drift[0].actual

    def test_showroom_mismatch_detected(self):
        constraints = {
            "showroom_repo": "https://github.com/rhpds/some-showroom.git",
        }
        evidence = {
            "showroom_repo": "https://github.com/rhpds/different-showroom.git",
        }
        violations = classify_constraints(constraints, evidence)
        showroom = [v for v in violations if v.violation_type == "showroom_wrong_content"]
        assert len(showroom) == 1

    def test_ocp_version_mismatch(self):
        constraints = {"ocp_version": "4.20"}
        evidence = {"ocp_version": "4.18"}
        violations = classify_constraints(constraints, evidence)
        resource = [v for v in violations if v.violation_type == "resource_below_spec"]
        assert len(resource) == 1

    def test_empty_constraints_no_violations(self):
        violations = classify_constraints({}, {})
        assert violations == []


class TestUnresolvedWorkloadTemplates:
    """A Jinja expression is not a workload list.

    Live Nov 16 2026: the lab detail page showed "Constraint Violations (797)"
    for one catalog item because `workloads:` was a Jinja string and the count
    (and the classifier's iteration) used the string's 797 characters.
    """

    def test_jinja_string_is_carried_as_template(self, tmp_path):
        common = tmp_path / "common.yaml"
        common.write_text('workloads: "{{ (_base_workloads + _extra_workloads) }}"\n')

        constraints = load_lab_constraints(common)

        assert "workloads" not in constraints
        assert constraints["workloads_template"].startswith("{{")
        assert "workload_count" not in constraints

    def test_resolved_list_is_kept(self, tmp_path):
        common = tmp_path / "common.yaml"
        common.write_text(
            "workloads:\n"
            "  - agnosticd.core_workloads.ocp4_workload_rhacs\n"
            "  - agnosticd.showroom.ocp4_workload_showroom\n"
        )

        constraints = load_lab_constraints(common)

        assert constraints["workload_count"] == 2
        assert "workloads_template" not in constraints

    def test_string_workloads_produce_no_violations(self):
        constraints = {"workloads_template": "{{ base_workloads }}"}
        evidence = {"deployed_namespaces": ["showroom"]}

        assert classify_constraints(constraints, evidence) == []

    def test_non_string_entries_are_skipped(self):
        constraints = {
            "workloads": [
                {"unresolved": True},
                "agnosticd.core_workloads.ocp4_workload_rhacs",
            ],
        }
        evidence = {"deployed_namespaces": ["showroom"]}

        violations = classify_constraints(constraints, evidence)
        workload_violations = [
            v for v in violations if v.violation_type == "workload_not_deployed"
        ]
        assert len(workload_violations) == 1
        assert "rhacs" in workload_violations[0].expected


class TestLabDetailConstraintEvidence:
    """The detail endpoint must not invent violations without live evidence."""

    def test_no_evidence_means_no_violations(self):
        from api.routers.dashboard.views import _get_lab_constraint_violations

        constraints = {"workloads": ["agnosticd.core_workloads.ocp4_workload_rhacs"]}

        assert _get_lab_constraint_violations("ocp-field-asset-aws", constraints) == []

    def test_evidence_enables_classification(self):
        from api.routers.dashboard.views import _get_lab_constraint_violations

        constraints = {"workloads": ["agnosticd.core_workloads.ocp4_workload_rhacs"]}
        evidence = {"deployed_namespaces": ["rhacs"]}

        assert _get_lab_constraint_violations(
            "ocp-field-asset-aws", constraints, evidence
        ) == []
