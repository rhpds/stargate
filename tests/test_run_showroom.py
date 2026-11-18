"""Historical showroom context for a run.

The reviewer's blocker: a failed sandbox is deleted, so the showroom URL is
gone from the cluster. It is not gone from StarGate — Route and ShowroomHealth
evidence are retained — but nothing exposed it.
"""

from datetime import datetime, timezone


def _run(client, run_id="run-1", namespace="sandbox-abc12-zt-rhelbu"):
    r = client.post("/runs", json={
        "run_id": run_id,
        "demo_id": "zt-rhelbu",
        "namespace": namespace,
        "requested_by": "test",
    })
    assert r.status_code in (200, 201), r.text
    return run_id


def _evidence(db, run_id, kind, observed, ts=None):
    from db.models import EvidenceRecord
    from uuid import uuid4
    db.add(EvidenceRecord(
        evidence_id=f"ev-{kind}-{uuid4().hex[:8]}",
        run_id=run_id,
        stage_id="showroom-healthy",
        type=kind,
        source="test",
        observed=observed,
        result="fail",
        timestamp=ts or datetime.now(timezone.utc),
    ))
    db.commit()


class TestRunShowroom:
    def test_returns_the_probe_diagnostics(self, client, db):
        run_id = _run(client)
        _evidence(db, run_id, "ShowroomHealth", {
            "showroom_route_reachable": False,
            "route_url": "https://showroom-abc12.apps.example.com",
            "http_status": 503,
            "error": "HTTP 503",
            "catalog_item": "zt-rhel-bu-lab-developer-cnv",
        })

        body = client.get(f"/runs/{run_id}/showroom").json()

        assert body["route_url"] == "https://showroom-abc12.apps.example.com"
        assert body["http_status"] == 503
        assert body["error"] == "HTTP 503"
        assert body["catalog_item"] == "zt-rhel-bu-lab-developer-cnv"
        assert body["namespace"] == "sandbox-abc12-zt-rhelbu"

    def test_falls_back_to_route_and_endpoints_evidence(self, client, db):
        run_id = _run(client)
        _evidence(db, run_id, "Route", {
            "host": "showroom-abc12.apps.example.com",
            "admitted": True,
        })
        _evidence(db, run_id, "Endpoints", {
            "ready_endpoint_count": 0,
            "service_has_ready_endpoints": False,
        })

        body = client.get(f"/runs/{run_id}/showroom").json()

        assert body["route_url"] == "https://showroom-abc12.apps.example.com"
        assert body["http_status"] is None
        assert body["ready_endpoint_count"] == 0

    def test_unknown_run_is_404(self, client, db):
        assert client.get("/runs/nope/showroom").status_code == 404


class TestRouteSelection:
    def test_prefers_the_showroom_route_over_the_newest_route(self, client, db):
        from datetime import datetime, timezone, timedelta

        run_id = _run(client, run_id="run-2")
        now = datetime.now(timezone.utc)
        _evidence(db, run_id, "Route", {
            "host": "showroom-abc12.apps.example.com", "admitted": True,
        }, ts=now - timedelta(seconds=1))
        # The container view is newer — but it is not the showroom.
        _evidence(db, run_id, "Route", {
            "host": "containerview-abc12.apps.example.com", "admitted": True,
        }, ts=now)

        body = client.get(f"/runs/{run_id}/showroom").json()

        assert body["route_url"] == "https://showroom-abc12.apps.example.com"


class TestReadyEndpointAmbiguity:
    def test_does_not_sum_every_service_in_the_namespace(self, client, db):
        run_id = _run(client, run_id="run-3")
        _evidence(db, run_id, "Route", {"host": "showroom-abc12.apps.example.com"})
        for _ in range(3):
            _evidence(db, run_id, "Endpoints", {"ready_endpoint_count": 10})

        body = client.get(f"/runs/{run_id}/showroom").json()

        # Three services × 10 is not "30 showroom endpoints".
        assert body["ready_endpoint_count"] is None
