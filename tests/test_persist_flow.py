"""End-to-end persistence flow — collect evidence, evaluate, persist, query report and bundle."""

import pytest


class TestPersistFlow:
    def test_full_collect_evaluate_report_cycle(self, client):
        # 1. Create run
        resp = client.post("/runs", json={
            "run_id": "persist-test-001",
            "demo_id": "demo-simple-container",
            "namespace": "summit-demo-persist",
            "requested_by": "test",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201

        # 2. Start stage + submit evidence + evaluate (namespace-ready)
        resp = client.post("/runs/persist-test-001/stages/namespace-ready/start")
        assert resp.status_code == 201

        resp = client.post("/runs/persist-test-001/stages/namespace-ready/evidence", json={
            "type": "resource_state",
            "source": "oc",
            "observed": {"namespace_exists": True, "phase": "Active"},
            "result": "pass",
        })
        assert resp.status_code == 201

        resp = client.post("/runs/persist-test-001/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "pass"

        # 3. Start stage + submit evidence + evaluate (deployment-ready — failing)
        client.post("/runs/persist-test-001/stages/deployment-ready/start")
        client.post("/runs/persist-test-001/stages/deployment-ready/evidence", json={
            "type": "resource_state",
            "source": "oc",
            "observed": {
                "deployment_exists": True,
                "desired_replicas_ready": False,
                "no_crashloop_pods": False,
            },
            "result": "fail",
        })
        resp = client.post("/runs/persist-test-001/stages/deployment-ready/evaluate", json={
            "evidence": {
                "namespace_exists": True,
                "deployment_exists": True,
                "desired_replicas_ready": False,
                "no_crashloop_pods": False,
            },
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "fail"
        assert resp.json()["failure_class"] == "pods_crashlooping"

        # 4. Query report
        resp = client.get("/runs/persist-test-001/report")
        assert resp.status_code == 200
        report = resp.json()
        assert report["passed"] == 1
        assert report["failed"] == 1
        assert len(report["stages"]) == 2

        ns_stage = next(s for s in report["stages"] if s["stage_id"] == "namespace-ready")
        assert ns_stage["outcome"] == "pass"
        assert ns_stage["evidence_count"] == 1

        dep_stage = next(s for s in report["stages"] if s["stage_id"] == "deployment-ready")
        assert dep_stage["outcome"] == "fail"
        assert dep_stage["failure_class"] == "pods_crashlooping"

        # 5. Query bundle
        resp = client.get("/runs/persist-test-001/bundle")
        assert resp.status_code == 200
        bundle = resp.json()
        assert bundle["run_id"] == "persist-test-001"
        assert len(bundle["current"]["stages"]) == 2

    def test_multiple_runs_build_history(self, client):
        for i in range(3):
            outcome = "pass" if i < 2 else "fail"
            evidence = {"namespace_exists": True} if i < 2 else {"namespace_exists": False}

            client.post("/runs", json={
                "run_id": f"history-run-{i}",
                "demo_id": "demo-simple-container",
                "namespace": "summit-demo-history",
                "requested_by": "test",
                "rubric_version": "v0.1.0",
            })
            client.post(f"/runs/history-run-{i}/stages/namespace-ready/start")
            client.post(f"/runs/history-run-{i}/stages/namespace-ready/evidence", json={
                "type": "resource_state",
                "source": "oc",
                "observed": evidence,
                "result": outcome,
            })
            client.post(f"/runs/history-run-{i}/stages/namespace-ready/evaluate", json={
                "evidence": evidence,
            })

        # All three runs should exist
        resp = client.get("/runs")
        assert len(resp.json()) == 3

        # Last run should be a failure
        resp = client.get("/runs/history-run-2/report")
        assert resp.json()["failed"] == 1

        # First two should be passes
        resp = client.get("/runs/history-run-0/report")
        assert resp.json()["passed"] == 1
