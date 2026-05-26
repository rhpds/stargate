"""VM and Model lane tests — collectors, normalizers, rubric evaluation, fixtures."""

import json
from pathlib import Path

import pytest

from api.app.models import StageOutcome
from api.app.rubric_evaluator import evaluate_rubric
from api.app.rubric_loader import load_rubric, load_rubrics_from_directory
from collectors.openshift.collect_resource_state import (
    collect_datavolume,
    collect_inferenceservice,
    collect_namespace_state,
    collect_pvc,
    collect_servingruntime,
    collect_vm,
    collect_vmi,
)
from collectors.openshift.evidence_normalizer import normalize_evidence


RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
VM_HEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "vm-healthy"
VM_UNHEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "vm-unhealthy"
MODEL_HEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "model-healthy"
MODEL_UNHEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "model-unhealthy"


def _load(path):
    return json.loads(path.read_text())


# --- VM Collector Tests ---

class TestDataVolumeCollector:
    def test_healthy_datavolume(self):
        ev = collect_datavolume(_load(VM_HEALTHY / "datavolume.json"))
        assert ev.resource_kind == "DataVolume"
        assert ev.observed["datavolume_exists"] is True
        assert ev.observed["datavolume_succeeded"] is True
        assert ev.observed["datavolume_phase"] == "Succeeded"
        assert ev.observed["pvc_bound"] is True

    def test_unhealthy_datavolume(self):
        ev = collect_datavolume(_load(VM_UNHEALTHY / "datavolume.json"))
        assert ev.observed["datavolume_exists"] is True
        assert ev.observed["datavolume_succeeded"] is False
        assert ev.observed["datavolume_phase"] == "ImportInProgress"


class TestPVCCollector:
    def test_bound_pvc(self):
        ev = collect_pvc(_load(VM_HEALTHY / "pvc.json"))
        assert ev.resource_kind == "PersistentVolumeClaim"
        assert ev.observed["pvc_bound"] is True
        assert ev.observed["pvc_capacity"] == "30Gi"

    def test_pending_pvc(self):
        ev = collect_pvc(_load(VM_UNHEALTHY / "pvc.json"))
        assert ev.observed["pvc_bound"] is False
        assert ev.observed["pvc_phase"] == "Pending"


class TestVMCollector:
    def test_healthy_vm(self):
        ev = collect_vm(_load(VM_HEALTHY / "vm.json"))
        assert ev.resource_kind == "VirtualMachine"
        assert ev.observed["vm_exists"] is True
        assert ev.observed["vm_ready"] is True
        assert ev.observed["vm_printable_status"] == "Running"

    def test_unhealthy_vm(self):
        ev = collect_vm(_load(VM_UNHEALTHY / "vm.json"))
        assert ev.observed["vm_exists"] is True
        assert ev.observed["vm_ready"] is False
        assert ev.observed["vm_printable_status"] == "WaitingForVolumeBinding"


class TestVMICollector:
    def test_healthy_vmi(self):
        ev = collect_vmi(_load(VM_HEALTHY / "vmi.json"))
        assert ev.resource_kind == "VirtualMachineInstance"
        assert ev.observed["vmi_running"] is True
        assert ev.observed["guest_agent_connected"] is True
        assert ev.observed["guest_os_ready"] is True
        assert ev.observed["guest_os_name"] == "Red Hat Enterprise Linux"
        assert ev.observed["ip_address"] == "10.128.2.50"

    def test_unhealthy_vmi(self):
        ev = collect_vmi(_load(VM_UNHEALTHY / "vmi.json"))
        assert ev.observed["vmi_running"] is False
        assert ev.observed["guest_agent_connected"] is False
        assert ev.observed["vmi_phase"] == "Scheduling"


# --- Model Collector Tests ---

class TestInferenceServiceCollector:
    def test_healthy_isvc(self):
        ev = collect_inferenceservice(_load(MODEL_HEALTHY / "inferenceservice.json"))
        assert ev.resource_kind == "InferenceService"
        assert ev.observed["inferenceservice_exists"] is True
        assert ev.observed["inferenceservice_ready"] is True
        assert ev.observed["model_loaded"] is True
        assert ev.observed["model_state"] == "Loaded"
        assert ev.observed["failure_reason"] is None

    def test_unhealthy_isvc(self):
        ev = collect_inferenceservice(_load(MODEL_UNHEALTHY / "inferenceservice.json"))
        assert ev.observed["inferenceservice_exists"] is True
        assert ev.observed["inferenceservice_ready"] is False
        assert ev.observed["model_loaded"] is False
        assert ev.observed["model_state"] == "FailedToLoad"
        assert ev.observed["failure_reason"] == "ModelLoadFailed"


class TestServingRuntimeCollector:
    def test_servingruntime(self):
        ev = collect_servingruntime(_load(MODEL_HEALTHY / "servingruntime.json"))
        assert ev.resource_kind == "ServingRuntime"
        assert ev.observed["servingruntime_exists"] is True
        assert "onnx" in ev.observed["supported_formats"]


# --- File collection for lanes ---

class TestLaneFileCollection:
    def test_collect_vm_healthy(self):
        results = collect_namespace_state(VM_HEALTHY)
        kinds = {r.resource_kind for r in results}
        assert "DataVolume" in kinds
        assert "PersistentVolumeClaim" in kinds
        assert "VirtualMachine" in kinds
        assert "VirtualMachineInstance" in kinds

    def test_collect_model_healthy(self):
        results = collect_namespace_state(MODEL_HEALTHY)
        kinds = {r.resource_kind for r in results}
        assert "InferenceService" in kinds
        assert "ServingRuntime" in kinds


# --- Normalizer Tests ---

class TestVMLaneNormalizer:
    def test_storage_clone_ready_healthy(self):
        evidence = collect_namespace_state(VM_HEALTHY)
        normalized = normalize_evidence("storage-clone-ready", evidence)
        assert normalized["namespace_exists"] is True
        assert normalized["datavolume_exists"] is True
        assert normalized["datavolume_succeeded"] is True
        assert normalized["pvc_bound"] is True

    def test_storage_clone_ready_unhealthy(self):
        evidence = collect_namespace_state(VM_UNHEALTHY)
        normalized = normalize_evidence("storage-clone-ready", evidence)
        assert normalized["datavolume_succeeded"] is False

    def test_vm_runtime_ready_healthy(self):
        evidence = collect_namespace_state(VM_HEALTHY)
        normalized = normalize_evidence("vm-runtime-ready", evidence)
        assert normalized["vm_exists"] is True
        assert normalized["vmi_running"] is True
        assert normalized["guest_agent_connected"] is True

    def test_vm_runtime_ready_unhealthy(self):
        evidence = collect_namespace_state(VM_UNHEALTHY)
        normalized = normalize_evidence("vm-runtime-ready", evidence)
        assert normalized["vmi_running"] is False
        assert normalized["guest_agent_connected"] is False


class TestModelLaneNormalizer:
    def test_model_endpoint_ready_healthy(self):
        evidence = collect_namespace_state(MODEL_HEALTHY)
        normalized = normalize_evidence("model-endpoint-ready", evidence)
        assert normalized["inferenceservice_exists"] is True
        assert normalized["inferenceservice_ready"] is True
        assert normalized["test_inference_succeeded"] is True

    def test_model_endpoint_ready_unhealthy(self):
        evidence = collect_namespace_state(MODEL_UNHEALTHY)
        normalized = normalize_evidence("model-endpoint-ready", evidence)
        assert normalized["inferenceservice_exists"] is True
        assert normalized["inferenceservice_ready"] is False
        assert normalized["test_inference_succeeded"] is False


# --- Full pipeline: collector -> normalizer -> rubric evaluator ---

class TestVMLaneRubricPipeline:
    def test_storage_clone_healthy_passes(self):
        rubric = load_rubric(RUBRIC_DIR / "storage-clone-ready.yaml")
        evidence = collect_namespace_state(VM_HEALTHY)
        normalized = normalize_evidence("storage-clone-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.PASS
        assert result.timeout_seconds == 600

    def test_storage_clone_unhealthy_fails(self):
        rubric = load_rubric(RUBRIC_DIR / "storage-clone-ready.yaml")
        evidence = collect_namespace_state(VM_UNHEALTHY)
        normalized = normalize_evidence("storage-clone-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "datavolume_failed"

    def test_vm_runtime_healthy_passes(self):
        rubric = load_rubric(RUBRIC_DIR / "vm-runtime-ready.yaml")
        evidence = collect_namespace_state(VM_HEALTHY)
        normalized = normalize_evidence("vm-runtime-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.PASS

    def test_vm_runtime_unhealthy_fails(self):
        rubric = load_rubric(RUBRIC_DIR / "vm-runtime-ready.yaml")
        evidence = collect_namespace_state(VM_UNHEALTHY)
        normalized = normalize_evidence("vm-runtime-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL

    def test_vm_runtime_unhealthy_entry_gate_blocks(self):
        rubric = load_rubric(RUBRIC_DIR / "vm-runtime-ready.yaml")
        evidence = collect_namespace_state(VM_UNHEALTHY)
        normalized = normalize_evidence("vm-runtime-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert "Entry criterion" in result.message


class TestModelLaneRubricPipeline:
    def test_model_endpoint_healthy_passes(self):
        rubric = load_rubric(RUBRIC_DIR / "model-endpoint-ready.yaml")
        evidence = collect_namespace_state(MODEL_HEALTHY)
        normalized = normalize_evidence("model-endpoint-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.PASS
        assert result.timeout_seconds == 900

    def test_model_endpoint_unhealthy_fails(self):
        rubric = load_rubric(RUBRIC_DIR / "model-endpoint-ready.yaml")
        evidence = collect_namespace_state(MODEL_UNHEALTHY)
        normalized = normalize_evidence("model-endpoint-ready", evidence)
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "inferenceservice_not_ready"


# --- Rubric loading ---

class TestLaneRubricLoading:
    def test_all_platform_rubrics_load(self):
        rubrics = load_rubrics_from_directory(RUBRIC_DIR)
        ids = {r.id for r in rubrics}
        assert "storage-clone-ready" in ids
        assert "vm-runtime-ready" in ids
        assert "model-endpoint-ready" in ids

    def test_all_lane_rubrics_have_timeout(self):
        for name in ["storage-clone-ready", "vm-runtime-ready", "model-endpoint-ready"]:
            rubric = load_rubric(RUBRIC_DIR / f"{name}.yaml")
            assert rubric.timeout_seconds is not None
            assert rubric.timeout_seconds > 0
