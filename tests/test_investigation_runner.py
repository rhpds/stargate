"""Tests for multi-step investigation chain runner."""

import json
from unittest.mock import patch

import pytest

from engine.investigation_runner import InvestigationRunner


@pytest.fixture
def runner():
    return InvestigationRunner()


class TestCheckCondition:
    """Tests for _check_condition truthy and contains checks."""

    def test_truthy_nonempty_list(self, runner):
        assert runner._check_condition("pods", {"pods": ["pod-a", "pod-b"]}) is True

    def test_truthy_empty_list(self, runner):
        assert runner._check_condition("pods", {"pods": []}) is False

    def test_truthy_none(self, runner):
        assert runner._check_condition("pods", {}) is False

    def test_truthy_nonempty_string(self, runner):
        assert runner._check_condition("desc", {"desc": "CrashLoopBackOff detected"}) is True

    def test_truthy_empty_string(self, runner):
        assert runner._check_condition("desc", {"desc": ""}) is False

    def test_truthy_whitespace_string(self, runner):
        assert runner._check_condition("desc", {"desc": "   "}) is False

    def test_truthy_nonempty_dict(self, runner):
        assert runner._check_condition("data", {"data": {"key": "val"}}) is True

    def test_truthy_empty_dict(self, runner):
        assert runner._check_condition("data", {"data": {}}) is False

    def test_truthy_boolean_true(self, runner):
        assert runner._check_condition("flag", {"flag": True}) is True

    def test_truthy_boolean_false(self, runner):
        assert runner._check_condition("flag", {"flag": False}) is False

    def test_contains_match(self, runner):
        assert runner._check_condition(
            "pod_description contains CrashLoopBackOff",
            {"pod_description": "State: CrashLoopBackOff, restarts: 5"},
        ) is True

    def test_contains_no_match(self, runner):
        assert runner._check_condition(
            "pod_description contains CrashLoopBackOff",
            {"pod_description": "State: Running, ready: true"},
        ) is False

    def test_contains_missing_var(self, runner):
        assert runner._check_condition(
            "pod_description contains CrashLoopBackOff",
            {},
        ) is False

    def test_contains_list_value_nonempty(self, runner):
        """When 'contains' target is a list, check list is non-empty."""
        assert runner._check_condition(
            "pods contains anything",
            {"pods": ["pod-a"]},
        ) is True

    def test_contains_list_value_empty(self, runner):
        assert runner._check_condition(
            "pods contains anything",
            {"pods": []},
        ) is False


class TestExtract:
    """Tests for _extract with JSON and non-JSON output."""

    def test_filter_expression(self, runner):
        data = {
            "items": [
                {"metadata": {"name": "pod-a"}, "status": {"phase": "Running"}},
                {"metadata": {"name": "pod-b"}, "status": {"phase": "Failed"}},
                {"metadata": {"name": "pod-c"}, "status": {"phase": "Pending"}},
            ]
        }
        result = runner._extract(
            json.dumps(data),
            "items[?(@.status.phase!='Running')].metadata.name",
        )
        assert result == ["pod-b", "pod-c"]

    def test_wildcard_expression(self, runner):
        data = {
            "items": [
                {"metadata": {"name": "pod-a"}},
                {"metadata": {"name": "pod-b"}},
            ]
        }
        result = runner._extract(
            json.dumps(data),
            "items[*].metadata.name",
        )
        assert result == ["pod-a", "pod-b"]

    def test_filter_equality(self, runner):
        data = {
            "items": [
                {"metadata": {"name": "pod-a"}, "status": {"phase": "Running"}},
                {"metadata": {"name": "pod-b"}, "status": {"phase": "Failed"}},
            ]
        }
        result = runner._extract(
            json.dumps(data),
            "items[?(@.status.phase=='Running')].metadata.name",
        )
        assert result == ["pod-a"]

    def test_non_json_output(self, runner):
        result = runner._extract(
            "NAME   READY   STATUS\npod-a  1/1     Running",
            "items[*].metadata.name",
        )
        assert result == "NAME   READY   STATUS\npod-a  1/1     Running"

    def test_empty_items(self, runner):
        data = {"items": []}
        result = runner._extract(
            json.dumps(data),
            "items[?(@.status.phase!='Running')].metadata.name",
        )
        assert result == []


class TestSubstitute:
    """Tests for _substitute with simple and indexed access."""

    def test_simple_variable(self, runner):
        result = runner._substitute(
            "oc get pods -n {namespace}",
            {"namespace": "test-ns"},
        )
        assert result == "oc get pods -n test-ns"

    def test_multiple_variables(self, runner):
        result = runner._substitute(
            "oc describe pod {pod} -n {namespace}",
            {"pod": "my-pod", "namespace": "test-ns"},
        )
        assert result == "oc describe pod my-pod -n test-ns"

    def test_indexed_access(self, runner):
        result = runner._substitute(
            "oc describe pod {failed_pods[0]} -n {namespace}",
            {"failed_pods": ["pod-a", "pod-b"], "namespace": "test-ns"},
        )
        assert result == "oc describe pod pod-a -n test-ns"

    def test_indexed_access_second_element(self, runner):
        result = runner._substitute(
            "oc logs {pods[1]}",
            {"pods": ["pod-a", "pod-b"]},
        )
        assert result == "oc logs pod-b"

    def test_indexed_access_out_of_range(self, runner):
        result = runner._substitute(
            "oc describe pod {failed_pods[5]} -n {namespace}",
            {"failed_pods": ["pod-a"], "namespace": "test-ns"},
        )
        assert result == "oc describe pod  -n test-ns"

    def test_list_without_index(self, runner):
        result = runner._substitute(
            "echo {pods}",
            {"pods": ["pod-a", "pod-b", "pod-c"]},
        )
        assert result == "echo pod-a pod-b pod-c"

    def test_missing_variable(self, runner):
        result = runner._substitute(
            "oc get {resource} -n {namespace}",
            {"namespace": "test-ns"},
        )
        assert result == "oc get  -n test-ns"


class TestFormatOutput:
    """Tests for _format_output with templates and context."""

    def test_with_template(self, runner):
        template = "## Report\nPods: {failed_pods}\nNamespace: {namespace}"
        context = {"namespace": "test-ns", "failed_pods": ["pod-a", "pod-b"]}
        result = runner._format_output(template, context)
        assert "pod-a pod-b" in result
        assert "test-ns" in result

    def test_without_template(self, runner):
        context = {
            "namespace": "test-ns",
            "pod_description": "This is a long pod description that exceeds twenty characters",
        }
        result = runner._format_output("", context)
        assert "## pod_description" in result
        assert "This is a long pod description" in result
        assert "namespace" not in result

    def test_without_template_short_values_excluded(self, runner):
        context = {"namespace": "test-ns", "short": "tiny"}
        result = runner._format_output("", context)
        assert result == ""


class TestRunFullChain:
    """Integration tests for the full run() method with mocked _run_oc."""

    @patch("engine.investigation_runner._run_oc")
    def test_steps_execute_in_order(self, mock_run_oc, runner):
        pods_json = json.dumps({
            "items": [
                {"metadata": {"name": "pod-a"}, "status": {"phase": "Failed"}},
                {"metadata": {"name": "pod-b"}, "status": {"phase": "Running"}},
            ]
        })
        mock_run_oc.side_effect = [
            pods_json,
            "Name: pod-a\nState: CrashLoopBackOff\nRestarts: 5",
            "Error: something crashed",
            "LAST SEEN   TYPE   REASON   MESSAGE",
        ]

        entry = {
            "steps": [
                {"command": "oc get pods -n {namespace} -o json",
                 "extract": "items[?(@.status.phase!='Running')].metadata.name",
                 "store_as": "failed_pods"},
                {"command": "oc describe pod {failed_pods[0]} -n {namespace}",
                 "condition": "failed_pods",
                 "store_as": "pod_description"},
                {"command": "oc logs {failed_pods[0]} -n {namespace} --previous --tail=50",
                 "condition": "pod_description contains CrashLoopBackOff",
                 "store_as": "crash_logs"},
                {"command": "oc get events -n {namespace} --sort-by=.lastTimestamp",
                 "store_as": "pod_events"},
            ],
            "output_template": "",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={})

        assert len(result["steps"]) == 4
        assert result["steps"][0]["command"] == "oc get pods -n test-ns -o json"
        assert result["steps"][1]["command"] == "oc describe pod pod-a -n test-ns"
        assert result["steps"][2]["command"] == "oc logs pod-a -n test-ns --previous --tail=50"
        assert result["context"]["failed_pods"] == ["pod-a"]
        assert "CrashLoopBackOff" in result["context"]["pod_description"]
        assert mock_run_oc.call_count == 4

    @patch("engine.investigation_runner._run_oc")
    def test_condition_skips_step(self, mock_run_oc, runner):
        pods_json = json.dumps({"items": []})
        mock_run_oc.side_effect = [
            pods_json,
            "LAST SEEN   TYPE   REASON   MESSAGE",
        ]

        entry = {
            "steps": [
                {"command": "oc get pods -n {namespace} -o json",
                 "extract": "items[?(@.status.phase!='Running')].metadata.name",
                 "store_as": "failed_pods"},
                {"command": "oc describe pod {failed_pods[0]} -n {namespace}",
                 "condition": "failed_pods",
                 "store_as": "pod_description"},
                {"command": "oc get events -n {namespace} --sort-by=.lastTimestamp",
                 "store_as": "pod_events"},
            ],
            "output_template": "",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={})

        # Step 1 (describe) should be skipped because failed_pods is empty
        assert len(result["steps"]) == 2
        assert result["steps"][0]["stored_as"] == "failed_pods"
        assert result["steps"][1]["stored_as"] == "pod_events"
        assert "pod_description" not in result["context"]
        assert mock_run_oc.call_count == 2

    @patch("engine.investigation_runner._run_oc")
    def test_context_accumulates(self, mock_run_oc, runner):
        mock_run_oc.side_effect = [
            "svc-a svc-b",
            "ep-1 ep-2",
        ]

        entry = {
            "steps": [
                {"command": "oc get svc -n {namespace}", "store_as": "services"},
                {"command": "oc get endpoints -n {namespace}", "store_as": "endpoints"},
            ],
            "output_template": "",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={"service": "my-svc"})

        assert result["context"]["namespace"] == "test-ns"
        assert result["context"]["service"] == "my-svc"
        assert result["context"]["services"] == "svc-a svc-b"
        assert result["context"]["endpoints"] == "ep-1 ep-2"

    @patch("engine.investigation_runner._run_oc")
    def test_params_available_in_context(self, mock_run_oc, runner):
        mock_run_oc.return_value = "OK"

        entry = {
            "steps": [
                {"command": "oc describe svc {service} -n {namespace}", "store_as": "detail"},
            ],
            "output_template": "",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={"service": "my-svc"})

        assert result["steps"][0]["command"] == "oc describe svc my-svc -n test-ns"

    @patch("engine.investigation_runner._run_oc")
    def test_step_failure_captured(self, mock_run_oc, runner):
        mock_run_oc.side_effect = Exception("connection refused")

        entry = {
            "steps": [
                {"command": "oc get pods -n {namespace}", "store_as": "pods"},
            ],
            "output_template": "",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={})

        assert len(result["steps"]) == 1
        assert "Error: connection refused" in result["steps"][0]["output"]
        assert "Error: connection refused" in result["context"]["pods"]

    @patch("engine.investigation_runner._run_oc")
    def test_output_template_rendered(self, mock_run_oc, runner):
        mock_run_oc.side_effect = ["pod-a pod-b", "event-1 event-2"]

        entry = {
            "steps": [
                {"command": "oc get pods -n {namespace}", "store_as": "pods"},
                {"command": "oc get events -n {namespace}", "store_as": "events"},
            ],
            "output_template": "## Report for {namespace}\nPods: {pods}\nEvents: {events}\n",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={})

        assert "## Report for test-ns" in result["report"]
        assert "Pods: pod-a pod-b" in result["report"]
        assert "Events: event-1 event-2" in result["report"]

    @patch("engine.investigation_runner._run_oc")
    def test_chained_contains_condition(self, mock_run_oc, runner):
        """Verify that a contains condition on a previous step's output works."""
        mock_run_oc.side_effect = [
            "Status: Running normally, no issues",
            "LAST SEEN   TYPE   REASON   MESSAGE",
        ]

        entry = {
            "steps": [
                {"command": "oc describe pod my-pod -n {namespace}",
                 "store_as": "pod_description"},
                {"command": "oc logs my-pod -n {namespace} --previous",
                 "condition": "pod_description contains CrashLoopBackOff",
                 "store_as": "crash_logs"},
                {"command": "oc get events -n {namespace}",
                 "store_as": "events"},
            ],
            "output_template": "",
        }

        result = runner.run(entry, namespace="test-ns", kubeconfig="/tmp/kube", params={})

        # Crash logs step should be skipped since description doesn't contain CrashLoopBackOff
        assert len(result["steps"]) == 2
        assert result["steps"][0]["stored_as"] == "pod_description"
        assert result["steps"][1]["stored_as"] == "events"
        assert "crash_logs" not in result["context"]


class TestGetNested:
    """Tests for _get_nested helper."""

    def test_simple_path(self, runner):
        assert runner._get_nested({"name": "pod-a"}, "name") == "pod-a"

    def test_deep_path(self, runner):
        obj = {"metadata": {"name": "pod-a", "labels": {"app": "web"}}}
        assert runner._get_nested(obj, "metadata.name") == "pod-a"
        assert runner._get_nested(obj, "metadata.labels.app") == "web"

    def test_missing_key(self, runner):
        assert runner._get_nested({"metadata": {"name": "pod-a"}}, "status.phase") is None

    def test_non_dict_intermediate(self, runner):
        assert runner._get_nested({"metadata": "string-value"}, "metadata.name") is None


class TestCompare:
    """Tests for _compare helper."""

    def test_not_equal(self, runner):
        assert runner._compare("Failed", "!=", "Running") is True
        assert runner._compare("Running", "!=", "Running") is False

    def test_equal(self, runner):
        assert runner._compare("Running", "==", "Running") is True
        assert runner._compare("Failed", "==", "Running") is False

    def test_unsupported_op(self, runner):
        assert runner._compare("5", ">", "3") is False
