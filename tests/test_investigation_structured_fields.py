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
