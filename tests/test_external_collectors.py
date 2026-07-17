"""Tests for Labagator, Demolition, and Babylon worker collectors.

These collectors call external APIs, so tests use mocking.
"""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestLabagatorCollector:
    @patch("collectors.labagator.collect_labagator._get")
    def test_collect_labs(self, mock_get):
        mock_get.return_value = [
            {"lab_code": "LB1088", "title": "Code Red", "status": "in_development", "cloud": "CNV"},
            {"lab_code": "LB1237", "title": "RHEL 10", "status": "planning", "cloud": "CNV"},
        ]
        from collectors.labagator.collect_labagator import collect_labs
        labs = collect_labs()
        assert len(labs) == 2
        assert labs[0]["lab_code"] == "LB1088"

    @patch("collectors.labagator.collect_labagator._get")
    def test_collect_sessions(self, mock_get):
        mock_get.return_value = [
            {"lab_code": "LB1088", "session_date": "2026-05-12", "start_time": "09:00:00",
             "room": "Room 1", "attendees": 60, "status": "planned"},
        ]
        from collectors.labagator.collect_labagator import collect_sessions
        sessions = collect_sessions()
        assert len(sessions) == 1
        assert sessions[0]["attendees"] == 60

    @patch("collectors.labagator.collect_labagator._get")
    def test_summarize_labs(self, mock_get):
        def side_effect(url):
            if "labs" in url:
                return [
                    {"lab_code": "LB1088", "title": "Code Red", "status": "in_development",
                     "cloud": "CNV", "deploy_mode": "per_attendee", "ci_name": "lb1088"},
                    {"lab_code": "LB1237", "title": "RHEL 10", "status": "planning",
                     "cloud": "CNV", "deploy_mode": None, "ci_name": None},
                ]
            if "sessions" in url:
                return [
                    {"lab_code": "LB1088", "session_date": "2026-05-12", "start_time": "09:00:00",
                     "room": "Room 1", "attendees": 60, "status": "planned"},
                    {"lab_code": "LB1088", "session_date": "2026-05-13", "start_time": "14:00:00",
                     "room": "Room 2", "attendees": 60, "status": "planned"},
                ]
            if "events" in url:
                return [{"id": 1, "name": "Summit 2026"}]
            return []

        mock_get.side_effect = side_effect
        from collectors.labagator.collect_labagator import summarize_labs
        result = summarize_labs()
        assert result["total_labs"] == 2
        assert result["total_sessions"] == 2
        assert result["status_counts"]["in_development"] == 1
        assert result["status_counts"]["planning"] == 1
        assert "LB1088" in result["labs_by_code"]
        assert result["labs_by_code"]["LB1088"]["session_count"] == 2

    @patch("collectors.labagator.collect_labagator._get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_get.return_value = None
        from collectors.labagator.collect_labagator import collect_labs
        assert collect_labs() == []


class TestDemolitionCollector:
    @patch("collectors.demolition.collect_demolition._get")
    def test_collect_sessions(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "name": "LB1088 test", "status": "completed", "worker_count": 10,
             "last_result": {"total": 10, "completed": 8, "failed": 2}},
        ]
        from collectors.demolition.collect_demolition import collect_sessions
        sessions = collect_sessions()
        assert len(sessions) == 1
        assert sessions[0]["status"] == "completed"

    @patch("collectors.demolition.collect_demolition._get")
    def test_summarize_sessions(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "name": "Session A", "status": "completed", "worker_count": 10,
             "last_result": {"total": 10, "completed": 8, "failed": 2}, "workshop_url": ""},
            {"id": 2, "name": "Session B", "status": "failed", "worker_count": 5,
             "last_result": {"total": 5, "completed": 0, "failed": 5}, "workshop_url": ""},
            {"id": 3, "name": "Session C", "status": "completed", "worker_count": 20,
             "last_result": {"total": 20, "completed": 20, "failed": 0}, "workshop_url": ""},
        ]
        from collectors.demolition.collect_demolition import summarize_sessions
        result = summarize_sessions()
        assert result["total_sessions"] == 3
        assert result["total_passed"] == 28
        assert result["total_failed"] == 7
        assert result["overall_pass_rate"] == 80.0
        assert len(result["failing_sessions"]) == 2

    @patch("collectors.demolition.collect_demolition._get")
    def test_find_summit_sessions(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "name": "Summit 2026 / LB1088", "status": "completed", "worker_count": 10,
             "last_result": {"total": 10, "completed": 7, "failed": 3}, "workshop_url": ""},
            {"id": 2, "name": "Other test", "status": "completed", "worker_count": 5,
             "last_result": {"total": 5, "completed": 5, "failed": 0}, "workshop_url": ""},
        ]
        from collectors.demolition.collect_demolition import find_summit_sessions
        summit = find_summit_sessions()
        assert len(summit) == 2
        assert summit[0]["name"] == "Summit 2026 / LB1088"
        assert summit[0]["failed"] == 3

    @patch("collectors.demolition.collect_demolition._get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_get.return_value = None
        from collectors.demolition.collect_demolition import collect_sessions
        assert collect_sessions() == []


class TestAnarchySummarizer:
    def test_summarize_subjects(self):
        from collectors.babylon.collect_anarchy_state import summarize_subjects
        subjects = [
            {"kind": "AnarchySubject", "metadata": {"name": "s1", "namespace": "ns"},
             "status": {"towerJobs": {"provision": {"completeTimestamp": "2026-01-01"}}},
             "spec": {"vars": {"current_state": "started"}}},
            {"kind": "AnarchySubject", "metadata": {"name": "s2", "namespace": "ns"},
             "status": {"towerJobs": {"provision": {}}},
             "spec": {"vars": {"current_state": "provision-failed"}}},
            {"kind": "AnarchySubject", "metadata": {"name": "s3", "namespace": "ns"},
             "status": {"towerJobs": {"provision": {"completeTimestamp": "2026-01-01"}}},
             "spec": {"vars": {"current_state": "started"}}},
        ]
        result = summarize_subjects(subjects)
        assert result["total_subjects"] == 3
        assert result["started"] == 2
        assert result["failed"] == 1
        assert result["failure_rate"] == pytest.approx(33.3, abs=0.1)


class TestWorkerTiers:
    def test_cluster_worker_init(self):
        from cli.worker import ClusterWorker
        w = ClusterWorker("test-cluster", "nonexistent-kc")
        assert w.state.name == "test-cluster"
        assert w.state.scan_count == 0
        assert w.TIER1_INTERVAL == 300
        assert w.TIER2_INTERVAL == 300
        assert w.TIER3_INTERVAL == 300

    def test_cluster_worker_not_available(self):
        from cli.worker import ClusterWorker
        w = ClusterWorker("test", "nonexistent-kubeconfig")
        assert not w.is_available()

    def test_cluster_state_defaults(self):
        from cli.worker import ClusterState
        state = ClusterState(name="test", kubeconfig="kc")
        assert state.scan_count == 0
        assert state.last_node_scan == 0
        assert state.last_pod_scan == 0
        assert state.last_ns_scan == 0
        assert len(state.failing_namespaces) == 0
        assert state.ns_rotation_index == 0


class TestDemoTypeDetection:
    def test_ocp4_cluster(self):
        from cli.worker import _detect_demo_type
        demo_id, stages = _detect_demo_type("sandbox-abc12-ocp4-cluster")
        assert demo_id == "ocp4-cluster"
        assert "vm-runtime-ready" in stages

    def test_zt_rhel(self):
        from cli.worker import _detect_demo_type
        demo_id, stages = _detect_demo_type("sandbox-xyz99-zt-rhelbu")
        assert demo_id == "zt-rhel"
        assert "deployment-ready" in stages

    def test_zt_ansible(self):
        from cli.worker import _detect_demo_type
        demo_id, stages = _detect_demo_type("sandbox-def45-zt-ansiblebu")
        assert demo_id == "zt-ansible"

    def test_numbered_variant(self):
        from cli.worker import _detect_demo_type
        demo_id, _ = _detect_demo_type("sandbox-ghi78-1-ocp4-cluster")
        assert demo_id == "ocp4-cluster"

    def test_double_numbered_variant(self):
        from cli.worker import _detect_demo_type
        demo_id, _ = _detect_demo_type("sandbox-jkl01-2-zt-ansiblebu")
        assert demo_id == "zt-ansible"

    def test_unknown_type_returns_suffix(self):
        from cli.worker import _detect_demo_type
        demo_id, stages = _detect_demo_type("sandbox-mno23-some-new-demo")
        assert demo_id == "some-new-demo"
        assert "namespace-ready" in stages


class TestScheduler:
    def test_scheduler_init(self):
        from cli.scheduler import Scheduler
        s = Scheduler(clusters={"test": "nonexistent"})
        assert len(s.workers) == 0

    def test_scheduler_stagger(self):
        from cli.scheduler import Scheduler
        # Use a mock clusters dict — workers won't start but we test offset calc
        s = Scheduler.__new__(Scheduler)
        s.workers = []
        s._shutdown = __import__("threading").Event()
        assert Scheduler.STAGGER_SECONDS == 30

    def test_worker_thread_init(self):
        from cli.scheduler import WorkerThread
        from cli.worker import ClusterWorker
        w = ClusterWorker("test", "kc")
        wt = WorkerThread(w, offset_seconds=60)
        assert wt.offset == 60
        assert wt.running is False
        assert wt.tick_count == 0
        assert wt.error_count == 0


class TestScanCLI:
    def test_scan_cluster_no_kubeconfig(self):
        from cli.scan import scan_cluster
        result = scan_cluster("nonexistent", "nonexistent-kc")
        assert result is None

    def test_clusters_config_exists(self):
        from cli.scan import CLUSTERS
        assert len(CLUSTERS) > 0
        assert "ocpv06" in CLUSTERS

    def test_format_text(self):
        from cli.scan import format_text
        results = [
            {"cluster": "test", "status": "healthy", "sandbox_active": 10,
             "total_vms": 50, "vms_per_node": 25, "avg_cpu_pct": 30,
             "hot_nodes": 0, "dns_warnings": 0, "sandbox_crashloop": 0,
             "issues": []},
        ]
        text = format_text(results)
        assert "test" in text
        assert "healthy" in text

    def test_format_slack_no_issues(self):
        from cli.scan import format_slack
        results = [
            {"cluster": "test", "status": "healthy", "issues": []},
        ]
        assert format_slack(results) is None

    def test_format_slack_with_critical(self):
        from cli.scan import format_slack
        results = [
            {"cluster": "test", "status": "critical", "avg_cpu_pct": 95,
             "total_vms": 100, "vms_per_node": 70, "issues": ["CPU overloaded"]},
        ]
        payload = format_slack(results)
        assert payload is not None
        assert "blocks" in payload
