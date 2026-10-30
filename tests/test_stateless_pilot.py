"""BDD contracts for an advisory-only, opt-in single-pod pilot."""
from datetime import datetime, timedelta, timezone

import pytest


def case():
    from engine.stateless_pilot import PilotPolicy, PilotEvidence
    server = "https://api.infra01.example.test:6443"
    now = datetime.now(timezone.utc)
    policy = PilotPolicy(server=server, cluster_uid="cluster-uid", namespace_uid="namespace-uid",
                         deployment="pilot-app", deployment_uid="deployment-uid", owner="operator")
    evidence = PilotEvidence(
        cluster="infra01", server=server, cluster_uid="cluster-uid", namespace="stargate-test",
        namespace_uid="namespace-uid", deployment="pilot-app", deployment_uid="deployment-uid",
        pod="pilot-app-abc", pod_uid="pod-uid", controller_deployment_uid="deployment-uid",
        observed_at=now, evidence_refs=["snapshot-1"], reviewer="operator",
        condition="confirmed_application_deadlock", restart_supported=True,
        consecutive_failed_probes=3, failure_duration_seconds=300,
        desired_replicas=2, ready_other_replicas=1, pdb_disruptions_allowed=1,
        stateless=True, dependencies_healthy=True, controller_healthy=True,
        persistent_storage_attached=False, pod_ready=False, confounding_failures=[],
        rollout_in_progress=False, deletion_in_progress=False, action_history_verified=True,
    )
    return now, policy, evidence


def test_opted_in_complete_case_is_review_candidate_never_execution():
    from engine.stateless_pilot import assess
    now, policy, evidence = case()
    result = assess(evidence, policy, now=now)
    assert result["status"] == "candidate_for_operator_review"
    assert result["execution_authorized"] is False
    assert result["approval_required"] is True
    assert result["evidence_trust"] == "caller_supplied_not_independently_verified"
    assert "commands" not in result


def test_missing_server_opt_in_blocks():
    from engine.stateless_pilot import assess
    now, _, evidence = case()
    assert "target_not_opted_in" in assess(evidence, None, now=now)["blockers"]


@pytest.mark.parametrize("changes,blocker", [
    ({"server": "https://api.ocpv06.example:6443"}, "target_identity_mismatch"),
    ({"cluster": "ocpv06"}, "target_identity_mismatch"),
    ({"namespace": "production"}, "target_identity_mismatch"),
    ({"cluster_uid": "wrong"}, "target_identity_mismatch"),
    ({"namespace_uid": "wrong"}, "target_identity_mismatch"),
    ({"deployment_uid": "wrong"}, "target_identity_mismatch"),
    ({"controller_deployment_uid": "wrong"}, "controller_identity_mismatch"),
    ({"pod_uid": ""}, "pod_identity_missing"),
    ({"stateless": False}, "stateful_or_storage_attached"),
    ({"persistent_storage_attached": True}, "stateful_or_storage_attached"),
    ({"condition": "readiness_probe_failed"}, "restart_not_justified"),
    ({"restart_supported": False}, "restart_not_justified"),
    ({"consecutive_failed_probes": 1}, "failure_not_persistent"),
    ({"desired_replicas": 1}, "availability_not_protected"),
    ({"ready_other_replicas": 0}, "availability_not_protected"),
    ({"pdb_disruptions_allowed": None}, "availability_not_protected"),
    ({"pdb_disruptions_allowed": 0}, "availability_not_protected"),
    ({"confounding_failures": ["storage_issue"]}, "confounding_failure"),
    ({"confounding_failures": ["unknown"]}, "confounding_failure"),
    ({"dependencies_healthy": False}, "dependency_or_controller_unhealthy"),
    ({"controller_healthy": False}, "dependency_or_controller_unhealthy"),
    ({"rollout_in_progress": True}, "rollout_or_deletion_in_progress"),
    ({"deletion_in_progress": True}, "rollout_or_deletion_in_progress"),
    ({"attempts_for_incident": 1}, "attempt_or_cooldown_limit"),
    ({"seconds_since_last_action": 60}, "attempt_or_cooldown_limit"),
    ({"reviewer": ""}, "review_or_evidence_missing"),
    ({"evidence_refs": []}, "review_or_evidence_missing"),
])
def test_unsafe_or_incomplete_case_refused(changes, blocker):
    from engine.stateless_pilot import assess
    now, policy, evidence = case()
    result = assess(evidence.model_copy(update=changes), policy, now=now)
    assert result["status"] == "blocked"
    assert blocker in result["blockers"]
    assert result["execution_authorized"] is False


@pytest.mark.parametrize("offset", [-121, 6])
def test_stale_or_future_snapshot_refused(offset):
    from engine.stateless_pilot import assess
    now, policy, evidence = case()
    evidence.observed_at = now + timedelta(seconds=offset)
    assert "evidence_not_fresh" in assess(evidence, policy, now=now)["blockers"]


def test_assessment_api_default_blocked_and_authenticated(client, monkeypatch):
    monkeypatch.delenv("STARGATE_STATELESS_PILOT_TARGET", raising=False)
    _, _, evidence = case()
    response = client.post("/admin/remediation/pilot/assess", json=evidence.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["blockers"] == ["target_not_opted_in"]
    assert response.json()["execution_authorized"] is False
    client.headers.pop("X-API-Key", None)
    assert client.post("/admin/remediation/pilot/assess", json={}).status_code in (401, 403)


def test_assessment_api_does_not_call_models_or_execute(client, monkeypatch):
    import json
    from api import llm, action_executor

    def forbidden(*args, **kwargs):
        raise AssertionError("Assessment must never call models or execute actions")

    monkeypatch.setattr(llm, "call_llm", forbidden)
    monkeypatch.setattr(action_executor, "execute_action", forbidden)
    _, policy, evidence = case()
    monkeypatch.setenv("STARGATE_STATELESS_PILOT_TARGET", policy.model_dump_json())
    result = client.post("/admin/remediation/pilot/assess", json=evidence.model_dump(mode="json"))
    assert result.status_code == 200
    assert result.json()["status"] == "candidate_for_operator_review"
    assert result.json()["execution_authorized"] is False
    assert "commands" not in json.dumps(result.json())


def test_invalid_policy_blocks_without_echoing_configuration(client, monkeypatch):
    monkeypatch.setenv("STARGATE_STATELESS_PILOT_TARGET", "invalid-private-configuration")
    _, _, evidence = case()
    response = client.post("/admin/remediation/pilot/assess", json=evidence.model_dump(mode="json"))
    assert response.status_code == 503
    assert "invalid-private-configuration" not in response.text


@pytest.mark.parametrize("field", ["persistent_storage_attached", "pod_ready", "rollout_in_progress",
                                    "deletion_in_progress", "pdb_disruptions_allowed", "action_history_verified"])
def test_missing_safety_evidence_defaults_to_blocked(field):
    from engine.stateless_pilot import PilotEvidence, assess
    now, policy, evidence = case()
    payload = evidence.model_dump()
    payload.pop(field)
    assert assess(PilotEvidence(**payload), policy, now=now)["status"] == "blocked"
