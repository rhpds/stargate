"""The deploy script's kubeconfig handling — the ocpv03 half of finding P0.6.

`scripts/deploy-infra01.sh` used to `oc delete secret stargate-kubeconfigs`
and recreate it from a hard-coded `--from-file` list. The list drifted from
`scanner.clusters` (it was missing `kubeconfig-ocpv03` and named files that
were not on disk), so every run of the script recreated the secret without a
credential for a cluster the scheduler was still told to scan. Nothing failed:
the scanner logs one "kubeconfig missing" line per cluster and then never
lists that cluster's namespaces, which looks exactly like a quiet fleet.

These tests run the real script against a stub `oc`, because the properties
worth pinning are in the shell: that a cluster with no credential anywhere
stops the run before the secret is written, and that the secret is merged
rather than deleted.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_DIR / "scripts" / "deploy-infra01.sh"
VALUES = PROJECT_DIR / "deploy" / "helm" / "stargate" / "values-infra01.yaml"
FLEET = ["ocpv03", "ocpv06", "ocpv07", "ocpv08", "ocpv09"]

# Captured before `tests/conftest.py` replaces `subprocess.Popen`.
_REAL_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def _run_the_script_for_real(monkeypatch):
    """Lift the no-subprocess guard for this module only.

    The guard exists to keep tests from reaching ambient clusters and
    services. These tests run `/bin/bash scripts/deploy-infra01.sh` with a
    `PATH` that contains nothing but stubs written into `tmp_path`, and every
    stub records its argv to a file instead of calling anything. What is
    under test is the shell — that a missing credential stops the run before
    the first `oc` call, and that the secret is applied rather than deleted —
    and none of that survives being reimplemented in Python.
    """
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)

OC_STUB = r"""#!/bin/bash
printf '%s\n' "$*" >> "$OC_LOG"
if [ "$1" = "whoami" ]; then
  if [ "$2" = "--show-server" ]; then
    echo "https://api.ocpv-infra01.example.com:6443"
    exit 0
  fi
  echo "jkershaw"
  exit 0
fi
case "$1" in
  new-project|project|adm|registry) exit 0 ;;
  create)
    printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: stargate-kubeconfigs\ntype: Opaque\ndata: {}\n'
    exit 0
    ;;
  apply)
    cat > /dev/null
    exit 0
    ;;
  get)
    if [ "$2" = "secret" ]; then
      if [ "${OC_SECRET_EXISTS:-1}" != "1" ]; then
        echo "Error from server (NotFound)" >&2
        exit 1
      fi
      case "$*" in
        *go-template*) printf '%s' "$OC_SECRET_KEYS" ;;
      esac
      exit 0
    fi
    exit 0
    ;;
esac
exit 0
"""


def _stub(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def _run(tmp_path, secrets=(), values=VALUES, args=(), live_keys=None, secret_exists=True,
         oc_body=OC_STUB):
    """Run the deploy script with stub `oc`/`helm` and a fake secrets dir."""
    bin_dir = _stub(tmp_path, "oc", oc_body).parent
    _stub(tmp_path, "helm", "#!/bin/bash\nexit 0\n")

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    for name in secrets:
        (secrets_dir / name).write_text("apiVersion: v1\nkind: Config\n")

    log = tmp_path / "oc.log"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "OC_LOG": str(log),
        "OC_SECRET_KEYS": "".join(f"{k}\n" for k in (live_keys or [])),
        "OC_SECRET_EXISTS": "1" if secret_exists else "0",
        "STARGATE_SECRETS_DIR": str(secrets_dir),
        "STARGATE_VALUES_FILE": str(values),
    }
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return result, log.read_text()


def _fleet_files(clusters=FLEET):
    return [f"kubeconfig-{c}" for c in clusters] + ["kubeconfig-executor"]


class TestFleetCoverage:
    def test_missing_fleet_kubeconfig_stops_before_the_secret_is_written(self, tmp_path):
        secrets = [f for f in _fleet_files() if f != "kubeconfig-ocpv06"]

        result, oc_log = _run(tmp_path, secrets=secrets, args=["--dry-run"])

        assert result.returncode == 1
        assert "kubeconfig-ocpv06" in result.stdout
        # It may look at the cluster to decide, but it must not have written
        # the secret: no create, no apply.
        assert "create secret" not in oc_log
        assert "apply" not in oc_log

    def test_a_credential_only_in_the_secret_is_accepted(self, tmp_path):
        """A laptop holding three of five kubeconfigs can still deploy.

        `oc apply` keeps the keys it does not mention, so a key that is
        already in the secret is coverage. Only having it in neither place —
        ocpv03 — is fatal.
        """
        secrets = [f for f in _fleet_files() if f != "kubeconfig-ocpv06"]

        result, _ = _run(
            tmp_path,
            secrets=secrets,
            args=["--dry-run"],
            live_keys=_fleet_files(),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "from the existing secret, no local copy to refresh: ocpv06" in result.stdout

    def test_missing_executor_is_required_because_the_chart_hard_codes_it(self, tmp_path):
        secrets = [f for f in _fleet_files() if f != "kubeconfig-executor"]

        result, oc_log = _run(tmp_path, secrets=secrets)

        assert result.returncode == 1
        assert "kubeconfig-executor" in result.stdout
        assert "create secret" not in oc_log

    def test_the_name_it_fails_on_is_read_from_the_values_file(self, tmp_path):
        values = tmp_path / "values.yaml"
        values.write_text('scanner:\n  clusters: "ocpv03,ocpv09"  # only two\n')

        result, _ = _run(
            tmp_path,
            secrets=["kubeconfig-ocpv03", "kubeconfig-executor"],
            values=values,
        )

        assert result.returncode == 1
        assert "kubeconfig-ocpv09" in result.stdout
        assert "kubeconfig-ocpv06" not in result.stdout

    def test_a_covered_fleet_proceeds(self, tmp_path):
        result, oc_log = _run(tmp_path, secrets=_fleet_files(), args=["--dry-run"])

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Deploying with Helm" in result.stdout
        # A dry run must not touch the secret.
        assert "create secret" not in oc_log


class TestSecretIsMerged:
    def test_the_script_never_deletes_the_secret(self):
        body = SCRIPT.read_text()
        # Comments are allowed to explain the old behaviour; only executed
        # lines matter here.
        commands = "\n".join(
            line for line in body.splitlines() if not line.lstrip().startswith("#")
        )

        assert "delete secret" not in commands
        assert "oc apply" in commands

    def test_apply_carries_every_kubeconfig_on_disk(self, tmp_path):
        secrets = _fleet_files() + ["kubeconfig-infra02", "kubeconfig-ocpv-infra01"]

        result, oc_log = _run(tmp_path, secrets=secrets)

        assert result.returncode == 0, result.stdout + result.stderr
        create = [line for line in oc_log.splitlines() if line.startswith("create secret")]
        assert len(create) == 1
        for name in secrets:
            assert f"--from-file={name}=" in create[0]
        assert "--dry-run=client -o yaml" in create[0]
        # The client-side render is piped into apply; the secret is never
        # replaced wholesale.
        assert "apply -f -" in oc_log


class TestVerifyMode:
    def test_verify_reports_a_cluster_with_no_credential_anywhere(self, tmp_path):
        secrets = [f for f in _fleet_files() if f != "kubeconfig-ocpv03"]
        live = [f for f in _fleet_files() if f != "kubeconfig-ocpv03"]

        result, oc_log = _run(
            tmp_path, secrets=secrets, args=["--verify-kubeconfigs"], live_keys=live
        )

        assert result.returncode == 1
        assert "kubeconfig-ocpv03" in result.stdout
        assert "MISSING" in result.stdout
        assert "create secret" not in oc_log
        assert "apply" not in oc_log

    def test_verify_passes_and_names_where_each_credential_comes_from(self, tmp_path):
        live = _fleet_files() + ["kubeconfig-ocpv05"]

        result, oc_log = _run(
            tmp_path, secrets=_fleet_files(), args=["--verify-kubeconfigs"], live_keys=live
        )

        assert result.returncode == 0, result.stdout
        assert "local + secret" in result.stdout
        assert "kubeconfig-ocpv05" in result.stdout  # listed, not fatal
        assert "create secret" not in oc_log

    def test_verify_reports_a_missing_secret(self, tmp_path):
        result, _ = _run(
            tmp_path, secrets=_fleet_files(), args=["--verify-kubeconfigs"], secret_exists=False
        )

        assert result.returncode == 0, result.stdout
        assert "does not exist" in result.stdout
        assert "local only (will be applied)" in result.stdout

    def test_verify_requires_a_connection(self, tmp_path):
        """It reads the live secret; it cannot answer half the question logged out."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "oc").write_text("#!/bin/bash\nexit 1\n")
        (bin_dir / "oc").chmod(0o755)
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        for name in _fleet_files():
            (secrets_dir / name).write_text("apiVersion: v1\n")

        result = subprocess.run(
            [shutil.which("bash") or "/bin/bash", str(SCRIPT), "--verify-kubeconfigs"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STARGATE_SECRETS_DIR": str(secrets_dir),
                "STARGATE_VALUES_FILE": str(VALUES),
            },
            timeout=120,
        )

        assert result.returncode == 1
        assert "not logged in" in result.stdout


class TestUsage:
    def test_unknown_argument_is_rejected(self, tmp_path):
        result, _ = _run(tmp_path, secrets=_fleet_files(), args=["--dryrun"])

        assert result.returncode == 2
        assert "--verify-kubeconfigs" in result.stdout


EXPIRED_TOKEN_STUB = r"""#!/bin/bash
printf '%s\n' "$*" >> "$OC_LOG"
if [ "$1" = "whoami" ] && [ "$2" = "--show-server" ]; then
  echo "https://api.ocpv-infra01.example.com:6443"
  exit 0
fi
if [ "$1" = "whoami" ]; then
  echo "error: You must be logged in to the server (Unauthorized)" >&2
  exit 1
fi
exit 1
"""


class TestConnection:
    def test_an_expired_token_is_not_a_connection(self, tmp_path):
        """`oc whoami --show-server` answers from the kubeconfig, not the cluster.

        A server URL that contains "infra01" therefore passed the connection
        check while every later call returned Unauthorized — the run died
        three steps in, on a command whose error said nothing about the cause.
        """
        result, oc_log = _run(
            tmp_path,
            secrets=_fleet_files(),
            args=["--dry-run"],
            oc_body=EXPIRED_TOKEN_STUB,
        )

        assert result.returncode == 1
        assert "token is not accepted" in result.stdout
        assert "oc login --server=" in result.stdout
        # Nothing beyond the two identity probes was attempted.
        assert oc_log.strip().splitlines() == ["whoami --show-server", "whoami"]
