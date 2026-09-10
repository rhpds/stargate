from tasks.maintenance import _extract_structured_fields


def test_extracts_numbered_markdown_sections_and_quality_fields():
    analysis = """
### 1. Diagnosis
The workload is unavailable.

### 2. Root Cause
The image reference points to a missing tag.

### 3. Remediation Strategy
Correct the reviewed catalog configuration.

### 4. Shadow Remediation
For human review only.

### 5. Owner
Lab owner

### 6. Verdict
ACTIONABLE

### 7. Confidence
85
"""

    fields = _extract_structured_fields(analysis)

    assert fields["root_cause"] == "The image reference points to a missing tag."
    assert fields["remediation_suggestion"] == "Correct the reviewed catalog configuration."
    assert fields["verdict"] == "ACTIONABLE"
    assert fields["confidence"] == 0.85


def test_extracts_legacy_bold_sections_and_decimal_confidence():
    analysis = """
**Root Cause**: A transient provisioning delay.

**Shadow Remediation**: Watch and wait.

**Verdict**: **TRANSIENT**
**Confidence**: **0.72**
"""

    fields = _extract_structured_fields(analysis)

    assert fields["root_cause"] == "A transient provisioning delay."
    assert fields["remediation_suggestion"] == "Watch and wait."
    assert fields["verdict"] == "TRANSIENT"
    assert fields["confidence"] == 0.72


def test_empty_analysis_has_no_quality_claims():
    assert _extract_structured_fields("") == {
        "root_cause": None,
        "remediation_suggestion": None,
        "verdict": None,
        "confidence": None,
    }


def test_usage_canary_assignment_is_stable(monkeypatch):
    from engine.investigation_agent import _usage_optimization_enabled

    monkeypatch.setenv("STARGATE_INVESTIGATION_USAGE_CANARY_PERCENT", "100")
    assert _usage_optimization_enabled("job-1") is True
    monkeypatch.setenv("STARGATE_INVESTIGATION_USAGE_CANARY_PERCENT", "0")
    assert _usage_optimization_enabled("job-1") is False


def test_evidence_sufficiency_requires_breadth_and_storage_diagnosis():
    from engine.investigation_agent import _evidence_sufficient

    common = [
        {"tool": "oc_read"},
        {"tool": "query_evaluations"},
        {"tool": "get_lab_identity"},
        {"tool": "get_resolution_history"},
        {"tool": "get_pool_status"},
    ]
    assert _evidence_sufficient("readiness_probe_failed", common) is True
    assert _evidence_sufficient("pvc_binding_failed", common) is False
    assert _evidence_sufficient("pvc_binding_failed", common + [{"tool": "get_storage_diagnosis"}]) is True
