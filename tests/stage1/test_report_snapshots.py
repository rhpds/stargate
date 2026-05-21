"""Golden file snapshot tests for run report output."""

from cli.run_report import format_run_report_text, format_run_report_yaml, RunReportData, StageReportData


def _make_pass_report() -> RunReportData:
    return RunReportData(
        run_id="local-demo-001",
        demo_id="demo-simple-container",
        namespace="summit-demo-001",
        status="completed",
        rubric_version="v0.1.0",
        stages=[
            StageReportData(stage_id="namespace-ready", status="pass", outcome="pass", evidence_count=1),
            StageReportData(stage_id="deployment-ready", status="pass", outcome="pass", evidence_count=4),
            StageReportData(stage_id="route-ready", status="pass", outcome="pass", evidence_count=5),
            StageReportData(stage_id="smoke-test-ready", status="pass", outcome="pass", evidence_count=4),
        ],
    )


def _make_fail_report() -> RunReportData:
    return RunReportData(
        run_id="local-demo-002",
        demo_id="demo-simple-container",
        namespace="summit-demo-002",
        status="failed",
        rubric_version="v0.1.0",
        stages=[
            StageReportData(stage_id="namespace-ready", status="pass", outcome="pass", evidence_count=1),
            StageReportData(stage_id="deployment-ready", status="pass", outcome="pass", evidence_count=4),
            StageReportData(
                stage_id="route-ready", status="fail", outcome="fail",
                failure_class="service_has_no_endpoints",
                message="Required criteria failed: service_has_ready_endpoints",
                evidence_count=5,
            ),
            StageReportData(
                stage_id="smoke-test-ready", status="fail", outcome="fail",
                message="Entry criterion not met: route_reachable",
                evidence_count=3,
            ),
        ],
    )


class TestPassReportSnapshot:
    def test_text_contains_all_stages(self):
        text = format_run_report_text(_make_pass_report())
        assert "Run Report: local-demo-001" in text
        assert "[+] namespace-ready: pass" in text
        assert "[+] deployment-ready: pass" in text
        assert "[+] route-ready: pass" in text
        assert "[+] smoke-test-ready: pass" in text

    def test_text_shows_summary(self):
        text = format_run_report_text(_make_pass_report())
        assert "4 passed, 0 failed, 0 warned, 4 total" in text

    def test_text_no_failed_section(self):
        text = format_run_report_text(_make_pass_report())
        assert "Failed Stages:" not in text

    def test_text_shows_evidence_counts(self):
        text = format_run_report_text(_make_pass_report())
        assert "[1 evidence]" in text
        assert "[5 evidence]" in text

    def test_yaml_contains_summary(self):
        yml = format_run_report_yaml(_make_pass_report())
        assert "passed: 4" in yml
        assert "failed: 0" in yml


class TestFailReportSnapshot:
    def test_text_shows_failures(self):
        text = format_run_report_text(_make_fail_report())
        assert "[X] route-ready: fail" in text
        assert "service_has_no_endpoints" in text

    def test_text_shows_failed_section(self):
        text = format_run_report_text(_make_fail_report())
        assert "Failed Stages:" in text
        assert "route-ready: service_has_no_endpoints" in text

    def test_text_shows_summary(self):
        text = format_run_report_text(_make_fail_report())
        assert "2 passed, 2 failed, 0 warned, 4 total" in text

    def test_yaml_shows_failure_class(self):
        yml = format_run_report_yaml(_make_fail_report())
        assert "failure_class: service_has_no_endpoints" in yml
        assert "failed: 2" in yml
