"""Unit tests for engine/failure_injector.py — safety, oc delegation, namespace enforcement."""

from unittest.mock import patch, MagicMock
import pytest

from engine.failure_injector import (
    _validate_namespace,
    _run_oc,
    INJECTORS,
    inject_failure,
    cleanup_all,
    ALLOWED_NAMESPACE,
)


# ---------------------------------------------------------------------------
# Namespace safety — the most critical property
# ---------------------------------------------------------------------------

class TestValidateNamespace:
    def test_accepts_test_namespace(self):
        _validate_namespace(ALLOWED_NAMESPACE)

    def test_rejects_production_namespace(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("sandbox-abc12-ocp4-cluster")

    def test_rejects_stargate_namespace(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("stargate")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("")

    def test_rejects_similar_names(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("stargate-test-2")

    def test_rejects_prefix_match(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("stargate-testing")


# ---------------------------------------------------------------------------
# _run_oc delegates to oc_runner.run_oc_traced
# ---------------------------------------------------------------------------

class TestRunOc:
    @patch("engine.failure_injector.run_oc_traced")
    def test_delegates_to_run_oc_traced(self, mock_traced):
        mock_traced.return_value = ("some output", {
            "command": "oc get pods", "output": "some output",
            "exit_code": 0, "duration_ms": 42,
        })
        result = _run_oc(["get", "pods", "-n", "stargate-test"])
        mock_traced.assert_called_once_with(
            ["get", "pods", "-n", "stargate-test"], kubeconfig="", timeout=30
        )
        assert result["exit_code"] == 0
        assert result["duration_ms"] == 42

    @patch("engine.failure_injector.run_oc_traced")
    def test_returns_trace_dict(self, mock_traced):
        trace = {"command": "oc delete pod x", "output": "deleted", "exit_code": 0, "duration_ms": 10}
        mock_traced.return_value = ("deleted", trace)
        result = _run_oc(["delete", "pod", "x"])
        assert result is trace

    @patch("engine.failure_injector.run_oc_traced")
    def test_passes_kubeconfig(self, mock_traced):
        mock_traced.return_value = ("", {"command": "", "output": "", "exit_code": 0, "duration_ms": 0})
        _run_oc(["get", "pods"], kubeconfig="/path/to/kc")
        mock_traced.assert_called_once_with(["get", "pods"], kubeconfig="/path/to/kc", timeout=30)


# ---------------------------------------------------------------------------
# ALL injectors must refuse non-test namespaces (parametrized)
# ---------------------------------------------------------------------------

ALL_INJECTOR_NAMES = list(INJECTORS.keys())


@pytest.mark.parametrize("failure_class", ALL_INJECTOR_NAMES)
class TestAllInjectorsNamespaceSafety:
    def test_rejects_production_namespace(self, failure_class):
        with pytest.raises(ValueError, match="BLOCKED"):
            INJECTORS[failure_class]("sandbox-abc12-ocp4-cluster")

    def test_rejects_stargate_main_namespace(self, failure_class):
        with pytest.raises(ValueError, match="BLOCKED"):
            INJECTORS[failure_class]("stargate")

    def test_rejects_default_namespace(self, failure_class):
        with pytest.raises(ValueError, match="BLOCKED"):
            INJECTORS[failure_class]("default")


# ---------------------------------------------------------------------------
# inject_failure() dispatch
# ---------------------------------------------------------------------------

class TestInjectFailure:
    def test_rejects_bad_namespace(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            inject_failure("pods_crashlooping", "production")

    @patch("engine.failure_injector.run_oc_traced")
    def test_dispatches_known_class(self, mock_traced):
        mock_traced.return_value = ("ok", {"command": "oc ...", "output": "ok", "exit_code": 0, "duration_ms": 5})
        result = inject_failure("pods_crashlooping", ALLOWED_NAMESPACE)
        assert result["failure_class"] == "pods_crashlooping"
        assert result["namespace"] == ALLOWED_NAMESPACE

    def test_returns_error_for_unknown_class(self):
        result = inject_failure("nonexistent_class", ALLOWED_NAMESPACE)
        assert "error" in result
        assert "available" in result

    def test_all_20_classes_registered(self):
        assert len(INJECTORS) == 20


# ---------------------------------------------------------------------------
# Representative injector tests — verify oc args and return structure
# ---------------------------------------------------------------------------

def _mock_trace(cmd_str="oc ...", output="created", exit_code=0):
    return (output, {"command": cmd_str, "output": output, "exit_code": exit_code, "duration_ms": 5})


class TestInjectPodsCrashlooping:
    @patch("engine.failure_injector.run_oc_traced")
    def test_creates_deployment_with_false_command(self, mock_traced):
        mock_traced.return_value = _mock_trace()
        result = INJECTORS["pods_crashlooping"](ALLOWED_NAMESPACE)
        assert result["failure_class"] == "pods_crashlooping"
        assert result["namespace"] == ALLOWED_NAMESPACE
        assert "deployment/proof-crashloop" in result["injected_resources"]
        assert len(result["commands"]) == 2
        calls = mock_traced.call_args_list
        create_call = calls[1][0][0]
        assert "create" in create_call
        assert "deployment" in create_call
        assert "/bin/false" in create_call


class TestInjectReadinessProbe:
    @patch("engine.failure_injector.run_oc_traced")
    def test_patches_readiness_probe(self, mock_traced):
        mock_traced.return_value = _mock_trace()
        result = INJECTORS["readiness_probe_failed"](ALLOWED_NAMESPACE)
        assert result["failure_class"] == "readiness_probe_failed"
        assert len(result["commands"]) == 3
        patch_call = mock_traced.call_args_list[2][0][0]
        assert "patch" in patch_call
        assert "proof-readiness" in patch_call


class TestInjectQuotaExceeded:
    @patch("engine.failure_injector.run_oc_traced")
    @patch("engine.failure_injector._apply_manifest")
    def test_creates_quota_then_exceeds(self, mock_apply, mock_traced):
        mock_traced.return_value = _mock_trace()
        mock_apply.return_value = {"command": "oc apply ...", "output": "created", "exit_code": 0, "duration_ms": 5}
        result = INJECTORS["quota_exceeded"](ALLOWED_NAMESPACE)
        assert result["failure_class"] == "quota_exceeded"
        assert "resourcequota/proof-quota" in result["injected_resources"]
        manifest = mock_apply.call_args[0][0]
        assert manifest["kind"] == "ResourceQuota"
        assert manifest["spec"]["hard"]["pods"] == "1"


class TestInjectVolumeMountFailed:
    @patch("engine.failure_injector.run_oc_traced")
    @patch("engine.failure_injector._apply_manifest")
    def test_references_nonexistent_secret(self, mock_apply, mock_traced):
        mock_traced.return_value = _mock_trace()
        mock_apply.return_value = {"command": "oc apply ...", "output": "created", "exit_code": 0, "duration_ms": 5}
        result = INJECTORS["volume_mount_failed"](ALLOWED_NAMESPACE)
        assert result["failure_class"] == "volume_mount_failed"
        manifest = mock_apply.call_args[0][0]
        volumes = manifest["spec"]["template"]["spec"]["volumes"]
        assert volumes[0]["secret"]["secretName"] == "nonexistent-secret-proof"


class TestInjectSchedulingFailed:
    @patch("engine.failure_injector.run_oc_traced")
    def test_impossible_node_selector(self, mock_traced):
        mock_traced.return_value = _mock_trace()
        result = INJECTORS["scheduling_failed"](ALLOWED_NAMESPACE)
        assert result["failure_class"] == "scheduling_failed"
        patch_call = mock_traced.call_args_list[2][0][0]
        assert "patch" in patch_call
        patch_json = [a for a in patch_call if "nonexistent-node-proof" in a]
        assert len(patch_json) == 1


# ---------------------------------------------------------------------------
# Return structure contract — all injectors must return consistent shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("failure_class", ALL_INJECTOR_NAMES)
class TestInjectorReturnContract:
    @patch("engine.failure_injector.run_oc_traced")
    @patch("engine.failure_injector._apply_manifest")
    def test_return_has_required_keys(self, mock_apply, mock_traced, failure_class):
        mock_traced.return_value = _mock_trace()
        mock_apply.return_value = {"command": "oc apply ...", "output": "created", "exit_code": 0, "duration_ms": 5}
        result = INJECTORS[failure_class](ALLOWED_NAMESPACE)
        assert "failure_class" in result
        assert "injected_resources" in result
        assert "namespace" in result
        assert "commands" in result
        assert result["failure_class"] == failure_class
        assert result["namespace"] == ALLOWED_NAMESPACE
        assert isinstance(result["commands"], list)
        assert len(result["commands"]) >= 1
        assert isinstance(result["injected_resources"], list)
        assert len(result["injected_resources"]) >= 1


# ---------------------------------------------------------------------------
# cleanup_all
# ---------------------------------------------------------------------------

class TestCleanupAll:
    def test_rejects_bad_namespace(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            cleanup_all("production")

    @patch("engine.failure_injector.run_oc_traced")
    def test_deletes_all_proof_resources(self, mock_traced):
        mock_traced.return_value = _mock_trace(output="deployment.apps \"proof-crashloop\" deleted")
        result = cleanup_all(ALLOWED_NAMESPACE)
        assert result["namespace"] == ALLOWED_NAMESPACE
        assert isinstance(result["deleted"], list)
        assert isinstance(result["commands"], list)
        assert len(result["commands"]) >= 16

    @patch("engine.failure_injector.run_oc_traced")
    def test_tracks_actually_deleted_resources(self, mock_traced):
        call_count = [0]
        def side_effect(args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("deployment.apps \"proof-crashloop\" deleted", {
                    "command": "oc delete ...", "output": 'deployment.apps "proof-crashloop" deleted',
                    "exit_code": 0, "duration_ms": 5,
                })
            return ("", {"command": "oc delete ...", "output": "", "exit_code": 0, "duration_ms": 2})
        mock_traced.side_effect = side_effect
        result = cleanup_all(ALLOWED_NAMESPACE)
        assert "deployment/proof-crashloop" in result["deleted"]
