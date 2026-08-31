from datetime import datetime, timedelta, timezone

from cli import babylon_worker


def _item(*, conditions=None, generation=1, observed_generation=1, age_hours=2):
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "metadata": {
            "name": "example-provision",
            "namespace": "babylon-catalog-prod",
            "generation": generation,
            "creationTimestamp": created.isoformat(),
            "labels": {"babylon.gpte.redhat.com/catalogItemName": "example-lab"},
        },
        "spec": {},
        "status": {
            "observedGeneration": observed_generation,
            "conditions": conditions or [],
        },
    }


def test_workshop_provision_query_failure_is_not_reported_as_zero(monkeypatch):
    monkeypatch.setattr(
        babylon_worker,
        "_oc_json_with_status",
        lambda *args, **kwargs: (None, {"ok": False, "error": "forbidden"}),
    )

    result = babylon_worker.collect_workshop_provisions()

    assert result["total"] is None
    assert result["query"]["ok"] is False
    assert "forbidden" in result["query"]["error"]
    assert result["findings"] == []


def test_failed_workshop_provision_is_actionable(monkeypatch):
    failed = {
        "type": "Failed",
        "status": "True",
        "reason": "TemplateError",
        "message": "unable to create workshop",
        "lastTransitionTime": datetime.now(timezone.utc).isoformat(),
    }
    monkeypatch.setattr(
        babylon_worker,
        "_oc_json_with_status",
        lambda *args, **kwargs: ({"items": [_item(conditions=[failed])]}, {"ok": True}),
    )

    result = babylon_worker.collect_workshop_provisions()

    assert result["total"] == 1
    assert result["finding_count"] == 1
    assert result["findings"][0]["failure_class"] == "workshop_provision_failed"
    assert result["findings"][0]["catalog_item"] == "example-lab"


def test_unobserved_generation_detects_controller_lag(monkeypatch):
    monkeypatch.setattr(
        babylon_worker,
        "_oc_json_with_status",
        lambda *args, **kwargs: (
            {"items": [_item(generation=4, observed_generation=3)]},
            {"ok": True},
        ),
    )

    result = babylon_worker.collect_workshop_provisions()

    assert result["findings"][0]["failure_class"] == "workshop_provision_controller_lag"


def test_old_not_ready_provision_is_stalled(monkeypatch):
    old_transition = datetime.now(timezone.utc) - timedelta(hours=2)
    not_ready = {
        "type": "Ready",
        "status": "False",
        "reason": "Reconciling",
        "lastTransitionTime": old_transition.isoformat(),
    }
    monkeypatch.setenv("STARGATE_WORKSHOP_PROVISION_STALL_HOURS", "1")
    monkeypatch.setattr(
        babylon_worker,
        "_oc_json_with_status",
        lambda *args, **kwargs: ({"items": [_item(conditions=[not_ready])]}, {"ok": True}),
    )

    result = babylon_worker.collect_workshop_provisions()

    assert result["findings"][0]["failure_class"] == "workshop_provision_stalled"


def test_successful_empty_query_is_distinct_from_failure(monkeypatch):
    monkeypatch.setattr(
        babylon_worker,
        "_oc_json_with_status",
        lambda *args, **kwargs: ({"items": []}, {"ok": True, "error": None}),
    )

    result = babylon_worker.collect_workshop_provisions()

    assert result["total"] == 0
    assert result["query"]["ok"] is True
    assert result["finding_count"] == 0
