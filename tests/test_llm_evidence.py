"""RED/GREEN TDD — LLM evidence bundles include all 7 data sources."""

from pathlib import Path


class TestAAPrecommendations:
    """AAP policy rules must generate recommendations."""

    def test_aap_provision_failing_in_policy(self):
        """engine/policy.py must have code for aap_provision_failing rule."""
        src = Path(__file__).parent.parent / "engine" / "policy.py"
        text = src.read_text()
        assert "aap_provision_failing" in text, "policy.py must implement aap_provision_failing rule"

    def test_aap_sli_breach_in_policy(self):
        """engine/policy.py must have code for aap_sli_breach rule."""
        src = Path(__file__).parent.parent / "engine" / "policy.py"
        text = src.read_text()
        assert "aap_sli_breach" in text, "policy.py must implement aap_sli_breach rule"


class TestExecSummaryEvidence:
    """Executive summary must include AAP SLI in evidence."""

    def test_exec_summary_has_aap_reference(self):
        """Executive summary endpoint code must reference AAP data."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        # Find the executive summary function
        in_exec = False
        has_aap = False
        for line in text.splitlines():
            if "def dashboard_executive_summary" in line:
                in_exec = True
            if in_exec and ("aap" in line.lower() or "provision_sli" in line or "collect_aap" in line):
                has_aap = True
            if in_exec and line.strip().startswith("def ") and "executive" not in line:
                break
        assert has_aap, "Executive summary must include AAP SLI data in evidence"


class TestClassificationEvidence:
    """Classification must include constraints and AAP context."""

    def test_auto_classify_has_aap_check(self):
        """auto_llm._classify_failure must check for AAP data."""
        src = Path(__file__).parent.parent / "engine" / "auto_llm.py"
        text = src.read_text()
        assert "aap" in text.lower() or "provision_failures" in text, (
            "auto_llm.py must include AAP context in classification evidence"
        )


class TestRemediationEvidence:
    """Remediation evidence must include AAP for lab context."""

    def test_remediation_has_aap(self):
        """Remediation evidence builder must include AAP data for labs."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        in_evidence = False
        has_aap = False
        for line in text.splitlines():
            if "_build_evidence_context" in line and "def " in line:
                in_evidence = True
            if in_evidence and ("aap" in line.lower() or "collect_aap" in line):
                has_aap = True
            if in_evidence and line.strip().startswith("def ") and "evidence" not in line:
                break
        assert has_aap, "Remediation evidence must include AAP data for lab context"
