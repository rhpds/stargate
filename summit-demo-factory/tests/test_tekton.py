"""Tekton integration tests — YAML validation, gate enforcement, pipeline simulation."""

from pathlib import Path

import pytest
import yaml

from api.app.models import StageOutcome
from collectors.tekton.pipeline_simulator import simulate_pipeline


TEKTON_TASKS_DIR = Path(__file__).parent.parent / "deploy" / "tekton" / "tasks"
TEKTON_PIPELINES_DIR = Path(__file__).parent.parent / "deploy" / "tekton" / "pipelines"
RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
HEALTHY_DIR = Path(__file__).parent.parent / "fixtures" / "oc" / "healthy"
UNHEALTHY_DIR = Path(__file__).parent.parent / "fixtures" / "oc" / "unhealthy"


# --- Tekton YAML schema validation ---

class TestTektonTaskYAML:
    """Validate that Task YAMLs are well-formed Tekton v1 resources."""

    def _load_task(self, name: str) -> dict:
        path = TEKTON_TASKS_DIR / name
        return yaml.safe_load(path.read_text())

    def test_create_run_task(self):
        task = self._load_task("sdf-create-run.yaml")
        assert task["apiVersion"] == "tekton.dev/v1"
        assert task["kind"] == "Task"
        assert task["metadata"]["name"] == "sdf-create-run"
        params = {p["name"] for p in task["spec"]["params"]}
        assert "demo-id" in params
        assert "namespace" in params
        results = {r["name"] for r in task["spec"]["results"]}
        assert "run-id" in results

    def test_collect_evidence_task(self):
        task = self._load_task("sdf-collect-evidence.yaml")
        assert task["kind"] == "Task"
        assert task["metadata"]["name"] == "sdf-collect-evidence"
        params = {p["name"] for p in task["spec"]["params"]}
        assert "run-id" in params
        assert "stage-id" in params
        assert "namespace" in params
        assert len(task["spec"]["steps"]) == 3

    def test_evaluate_gate_task(self):
        task = self._load_task("sdf-evaluate-gate.yaml")
        assert task["kind"] == "Task"
        assert task["metadata"]["name"] == "sdf-evaluate-gate"
        results = {r["name"] for r in task["spec"]["results"]}
        assert "outcome" in results
        assert "failure-class" in results

    def test_report_task(self):
        task = self._load_task("sdf-report.yaml")
        assert task["kind"] == "Task"
        assert task["metadata"]["name"] == "sdf-report"
        params = {p["name"] for p in task["spec"]["params"]}
        assert "run-id" in params

    def test_all_tasks_use_ubi_images(self):
        """All task steps must use Red Hat UBI or OpenShift CLI images."""
        allowed_prefixes = (
            "registry.access.redhat.com/",
            "registry.redhat.io/",
            "image-registry.openshift-image-registry",
        )
        for task_file in TEKTON_TASKS_DIR.glob("*.yaml"):
            task = yaml.safe_load(task_file.read_text())
            for step in task["spec"]["steps"]:
                image = step["image"]
                assert any(image.startswith(p) for p in allowed_prefixes), (
                    f"Task {task_file.name} step {step['name']} uses non-RH image: {image}"
                )

    def test_gate_task_exits_nonzero_on_fail(self):
        """The gate evaluate step script must contain 'exit 1' for fail case."""
        task = self._load_task("sdf-evaluate-gate.yaml")
        evaluate_step = task["spec"]["steps"][0]
        assert "exit 1" in evaluate_step["script"]


class TestTektonPipelineYAML:
    def test_pipeline_structure(self):
        path = TEKTON_PIPELINES_DIR / "demo-provision-pipeline.yaml"
        pipeline = yaml.safe_load(path.read_text())
        assert pipeline["apiVersion"] == "tekton.dev/v1"
        assert pipeline["kind"] == "Pipeline"
        assert pipeline["metadata"]["name"] == "sdf-demo-provision"

        task_names = [t["name"] for t in pipeline["spec"]["tasks"]]
        assert "create-run" in task_names
        assert "gate-namespace" in task_names
        assert "gate-deployment" in task_names
        assert "gate-route" in task_names
        assert "gate-smoke" in task_names

    def test_pipeline_has_finally_report(self):
        path = TEKTON_PIPELINES_DIR / "demo-provision-pipeline.yaml"
        pipeline = yaml.safe_load(path.read_text())
        finally_tasks = pipeline["spec"]["finally"]
        assert len(finally_tasks) >= 1
        assert finally_tasks[0]["name"] == "report"

    def test_pipeline_gates_run_after_collect(self):
        """Each gate must run after its corresponding collect task."""
        path = TEKTON_PIPELINES_DIR / "demo-provision-pipeline.yaml"
        pipeline = yaml.safe_load(path.read_text())
        tasks = {t["name"]: t for t in pipeline["spec"]["tasks"]}

        assert "collect-namespace" in tasks["gate-namespace"].get("runAfter", [])
        assert "collect-deployment" in tasks["gate-deployment"].get("runAfter", [])
        assert "collect-route" in tasks["gate-route"].get("runAfter", [])
        assert "collect-smoke" in tasks["gate-smoke"].get("runAfter", [])

    def test_pipeline_stages_are_sequential(self):
        """Gates must enforce sequential promotion."""
        path = TEKTON_PIPELINES_DIR / "demo-provision-pipeline.yaml"
        pipeline = yaml.safe_load(path.read_text())
        tasks = {t["name"]: t for t in pipeline["spec"]["tasks"]}

        assert "gate-namespace" in tasks["collect-deployment"].get("runAfter", [])
        assert "gate-deployment" in tasks["collect-route"].get("runAfter", [])
        assert "gate-route" in tasks["collect-smoke"].get("runAfter", [])

    def test_pipelinerun_references_pipeline(self):
        path = TEKTON_PIPELINES_DIR / "demo-provision-pipelinerun.yaml"
        pr = yaml.safe_load(path.read_text())
        assert pr["kind"] == "PipelineRun"
        assert pr["spec"]["pipelineRef"]["name"] == "sdf-demo-provision"


# --- Pipeline simulation tests ---

SMOKE_TEST_EVIDENCE = {
    "smoke-test-ready": {
        "smoke_test_passed": True,
        "expected_response_received": True,
        "response_time_acceptable": True,
    },
}


class TestPipelineSimulation:
    def test_healthy_pipeline_succeeds(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-001",
            oc_fixture_dir=HEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
            extra_evidence=SMOKE_TEST_EVIDENCE,
        )
        assert result.status == "succeeded"
        assert result.blocked_by is None
        assert all(g.gate_passed for g in result.gates)

    def test_healthy_all_gates_pass(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-001",
            oc_fixture_dir=HEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
            extra_evidence=SMOKE_TEST_EVIDENCE,
        )
        for gate in result.gates:
            assert gate.outcome in (StageOutcome.PASS, StageOutcome.WARN), (
                f"Gate {gate.stage_id} should pass but got {gate.outcome}"
            )

    def test_healthy_pipeline_fails_without_smoke_test(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-001",
            oc_fixture_dir=HEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
        )
        assert result.status == "failed"
        assert result.blocked_by == "smoke-test-ready"

    def test_unhealthy_pipeline_fails(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-002",
            oc_fixture_dir=UNHEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
        )
        assert result.status == "failed"
        assert result.blocked_by is not None

    def test_unhealthy_blocks_at_deployment(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-002",
            oc_fixture_dir=UNHEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
        )
        assert result.blocked_by == "deployment-ready"

    def test_unhealthy_skips_later_stages(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-002",
            oc_fixture_dir=UNHEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
        )
        skipped_tasks = [t for t in result.tasks if t.status == "skipped"]
        assert len(skipped_tasks) >= 2
        skipped_names = {t.task_name for t in skipped_tasks}
        assert "collect-route-ready" in skipped_names or "gate-route-ready" in skipped_names

    def test_report_always_runs(self):
        """Report task runs regardless of pipeline success/failure."""
        for fixture_dir in [HEALTHY_DIR, UNHEALTHY_DIR]:
            result = simulate_pipeline(
                demo_id="test",
                namespace="ns",
                oc_fixture_dir=fixture_dir,
                rubric_dir=RUBRIC_DIR,
            )
            report_tasks = [t for t in result.tasks if t.task_name == "report"]
            assert len(report_tasks) == 1
            assert report_tasks[0].status == "succeeded"

    def test_failure_class_propagated(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-002",
            oc_fixture_dir=UNHEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
        )
        deployment_gate = next(g for g in result.gates if g.stage_id == "deployment-ready")
        assert deployment_gate.failure_class == "pods_crashlooping"

    def test_gate_results_in_task_results(self):
        result = simulate_pipeline(
            demo_id="demo-simple-container",
            namespace="summit-demo-001",
            oc_fixture_dir=HEALTHY_DIR,
            rubric_dir=RUBRIC_DIR,
            extra_evidence=SMOKE_TEST_EVIDENCE,
        )
        gate_tasks = [t for t in result.tasks if t.task_name.startswith("gate-")]
        for gt in gate_tasks:
            if gt.status == "succeeded":
                assert "outcome" in gt.results
                assert gt.results["outcome"] == "pass"
