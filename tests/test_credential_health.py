"""Credential health — liveness, expiry and the failure classes they produce."""

import base64
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from collectors import credential_health as ch


def _jwt(expires_in_days: int = 365) -> str:
    payload = {
        "sub": "system:serviceaccount:default:stargate-scanner",
        "exp": int((datetime.now(timezone.utc) + timedelta(days=expires_in_days)).timestamp()),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


def _kubeconfig(tmp_path: Path, token: str) -> Path:
    path = tmp_path / "kubeconfig-ocpv06"
    path.write_text(
        "apiVersion: v1\nkind: Config\nusers:\n- name: stargate-scanner\n"
        f"  user:\n    token: {token}\n"
    )
    return path


class _Proc:
    def __init__(self, stdout: str, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr


class TestJwtExpiry:
    def test_reads_exp_claim(self):
        expires = ch._jwt_expiry(_jwt(30))
        assert expires is not None
        assert 28 <= (expires - datetime.now(timezone.utc)).days <= 30

    def test_opaque_token_returns_none(self):
        assert ch._jwt_expiry("not-a-jwt") is None


class TestKubeconfigProbe:
    def test_missing_file_is_a_named_failure(self, tmp_path):
        result = ch._probe_kubeconfig("kubeconfig:ocpv06", tmp_path / "nope")

        assert result["outcome"] == "fail"
        assert result["failure_class"] == "credential_missing"

    def test_live_token_passes(self, tmp_path, monkeypatch):
        path = _kubeconfig(tmp_path, _jwt(365))
        monkeypatch.setattr(ch.shutil, "which", lambda _: "/usr/bin/oc")
        monkeypatch.setattr(ch.subprocess, "run",
                            lambda *a, **k: _Proc("system:serviceaccount:default:stargate-scanner\n"))

        result = ch._probe_kubeconfig("kubeconfig:ocpv06", path)

        assert result["outcome"] == "pass"
        assert result["days_left"] is not None and result["days_left"] > 300

    def test_revoked_token_is_rejected(self, tmp_path, monkeypatch):
        path = _kubeconfig(tmp_path, _jwt(365))
        monkeypatch.setattr(ch.shutil, "which", lambda _: "/usr/bin/oc")
        monkeypatch.setattr(ch.subprocess, "run", lambda *a, **k: _Proc(
            "", "error: You must be logged in to the server (Unauthorized)"))

        result = ch._probe_kubeconfig("kubeconfig:ocpv06", path)

        assert result["outcome"] == "fail"
        assert result["failure_class"] == "credential_rejected"

    def test_expiring_token_warns(self, tmp_path, monkeypatch):
        path = _kubeconfig(tmp_path, _jwt(10))
        monkeypatch.setattr(ch.shutil, "which", lambda _: "/usr/bin/oc")
        monkeypatch.setattr(ch.subprocess, "run", lambda *a, **k: _Proc("system:serviceaccount:x:y\n"))

        result = ch._probe_kubeconfig("kubeconfig:ocpv06", path)

        assert result["outcome"] == "warn"
        assert result["failure_class"] == "credential_expiring"


class TestNoExpiryRule:
    """A JWT with no `exp` never dies — the legacy-token failure mode."""

    def _static_jwt(self):
        import base64, json
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "system:serviceaccount:default:stargate-scanner"}).encode()
        ).decode().rstrip("=")
        return f"header.{payload}.signature"

    def test_jwt_without_exp_fails(self, tmp_path, monkeypatch):
        monkeypatch.delenv("STARGATE_CREDENTIAL_EXPIRY_WAIVERS", raising=False)
        path = _kubeconfig(tmp_path, self._static_jwt())
        monkeypatch.setattr(ch.shutil, "which", lambda _: "/usr/bin/oc")
        monkeypatch.setattr(ch.subprocess, "run",
                            lambda *a, **k: _Proc("system:serviceaccount:default:stargate-scanner\n"))

        result = ch._probe_kubeconfig("kubeconfig:ocpv06", path)

        assert result["outcome"] == "fail"
        assert result["failure_class"] == "credential_no_expiry"

    def test_waiver_clears_the_rule(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ch, "EXPIRY_WAIVERS", {"kubeconfig:ocpv06"})
        path = _kubeconfig(tmp_path, self._static_jwt())
        monkeypatch.setattr(ch.shutil, "which", lambda _: "/usr/bin/oc")
        monkeypatch.setattr(ch.subprocess, "run",
                            lambda *a, **k: _Proc("system:serviceaccount:default:stargate-scanner\n"))

        result = ch._probe_kubeconfig("kubeconfig:ocpv06", path)

        assert result["outcome"] == "pass"

    def test_opaque_token_is_not_flagged(self, tmp_path, monkeypatch):
        path = _kubeconfig(tmp_path, "sha256~opaque-token-value")
        monkeypatch.setattr(ch.shutil, "which", lambda _: "/usr/bin/oc")
        monkeypatch.setattr(ch.subprocess, "run",
                            lambda *a, **k: _Proc("system:serviceaccount:default:stargate-scanner\n"))

        result = ch._probe_kubeconfig("kubeconfig:ocpv06", path)

        assert result["outcome"] == "pass"


class TestHttpProbe:
    def test_401_is_rejected(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)

        monkeypatch.setattr(ch.urllib.request, "urlopen", boom)
        result = ch._probe_http("github:x", "github", "TOKEN", "http://x")

        assert result["outcome"] == "fail"
        assert result["failure_class"] == "credential_rejected"

    def test_timeout_is_unreachable(self, monkeypatch):
        def boom(*args, **kwargs):
            raise TimeoutError()

        monkeypatch.setattr(ch.urllib.request, "urlopen", boom)
        result = ch._probe_http("github:x", "github", "TOKEN", "http://x")

        assert result["outcome"] == "fail"
        assert result["failure_class"] == "credential_unreachable"


class TestRunCheck:
    def test_summary_counts(self, monkeypatch):
        monkeypatch.setattr(ch, "_targets", lambda: [
            {"name": "a", "probe": lambda: ch._result("a", "kubeconfig", "s", "pass")},
            {"name": "b", "probe": lambda: ch._result("b", "kubeconfig", "s", "fail",
                                                      failure_class="credential_rejected")},
            {"name": "c", "probe": lambda: ch._result("c", "kubeconfig", "s", "warn",
                                                      failure_class="credential_expiring")},
        ])
        report = ch.run_credential_check(force=True)

        assert report["credentials_probed"] == 3
        assert report["failing"] == 1
        assert report["degraded"] == 1

    def test_a_broken_probe_does_not_stop_the_rest(self, monkeypatch):
        def explode():
            raise RuntimeError("nope")

        monkeypatch.setattr(ch, "_targets", lambda: [
            {"name": "bad", "probe": explode},
            {"name": "good", "probe": lambda: ch._result("good", "kubeconfig", "s", "pass")},
        ])
        report = ch.run_credential_check(force=True)

        assert report["credentials_probed"] == 1

    def test_persists_one_evaluation_per_credential(self, db, monkeypatch):
        results = [
            ch._result("kubeconfig:ocpv06", "kubeconfig", "secrets/x", "pass",
                       expires_at=datetime.now(timezone.utc) + timedelta(days=200)),
            ch._result("jira", "basic", "STARGATE_JIRA_TOKEN", "fail",
                       failure_class="credential_rejected"),
        ]
        count = ch.record_credential_evaluations({"results": results}, db)

        assert count == 2
        from db.models import EvaluationRecord
        rows = db.query(EvaluationRecord).filter_by(stage_id="credential-health").all()
        assert {r.cluster_name for r in rows} == {"kubeconfig:ocpv06", "jira"}
        assert {r.lab_code for r in rows} == {"(credential)"}


class TestCredentialsEndpoint:
    def test_returns_latest_per_credential(self, client, db):
        from db.models import EvaluationRecord
        db.add(EvaluationRecord(
            run_id="cred-health-a", stage_id="credential-health", outcome="fail",
            failure_class="credential_rejected", message="401",
            criteria_results=[{"kind": "kubeconfig", "source": "secrets/x",
                               "status": None, "expires_at": None, "days_left": None}],
            evaluated_at=datetime.now(timezone.utc), lab_code="(credential)",
            cluster_name="kubeconfig:ocpv06",
        ))
        db.add(EvaluationRecord(
            run_id="cred-health-b", stage_id="credential-health", outcome="pass",
            failure_class=None, message="system:serviceaccount:x:y",
            criteria_results=[{"kind": "github", "source": "TOKEN", "status": 200,
                               "expires_at": None, "days_left": None}],
            evaluated_at=datetime.now(timezone.utc), lab_code="(credential)",
            cluster_name="github:agnosticv",
        ))
        db.commit()

        response = client.get("/dashboard/credentials")

        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total"] == 2
        assert body["summary"]["rejected"] == 1
        assert body["summary"]["verified"] == 1
        # failures sort first
        assert body["credentials"][0]["credential"] == "kubeconfig:ocpv06"
