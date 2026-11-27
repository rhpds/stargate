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


# The next three shapes are taken from stored investigations whose verdict was
# NULL: the enum was present in every one, just not adjacent to the word
# "Verdict". 1,257 of 2,800 rows (45%) carried a null verdict for this reason.


def test_extracts_blockquote_verdict_under_a_heading():
    analysis = """
### 5. Owner
lab-owner

### 6. Verdict

> **TRANSIENT**

The namespace was cleanly reclaimed.

### 7. Confidence
90
"""

    fields = _extract_structured_fields(analysis)

    assert fields["verdict"] == "TRANSIENT"


def test_extracts_verdict_from_a_table_row():
    analysis = """
| Field | Value |
|---|---|
| Verdict | ACTIONABLE |
| Confidence | 70 |
"""

    assert _extract_structured_fields(analysis)["verdict"] == "ACTIONABLE"


def test_extracts_verdict_bolded_on_the_next_line():
    analysis = """
**Verdict**
**ACTIONABLE**
"""

    assert _extract_structured_fields(analysis)["verdict"] == "ACTIONABLE"


def test_prose_does_not_invent_a_verdict():
    # Lowercase prose was already safe; the false positives that reached the
    # database used the enum in upper case inside a sentence.
    lowercase = """
### 2. Root Cause
The failure looks transient in nature, but it is actionable information for the team.
"""
    assert _extract_structured_fields(lowercase)["verdict"] is None

    # id=2957: the adjective attached to a PVC, not a verdict.
    uppercase = """
## 3. Remediation Strategy

**For the postgres read-only PVC (primary — ACTIONABLE):**
The Ceph RBD volume needs to be investigated at the storage layer.
"""
    assert _extract_structured_fields(uppercase)["verdict"] is None

    # id=2867: the adjective applied to a pattern.
    pattern = """
### 3. Remediation Strategy

The `namespace_missing` alert is a false positive. However, the underlying
`teardown_stuck` pattern is ACTIONABLE and requires platform team intervention.
"""
    assert _extract_structured_fields(pattern)["verdict"] is None


def test_adjudication_summary_does_not_invent_a_verdict():
    # id=3052 (inv-5e0ae4cc): the agent stopped after two iterations with no
    # report sections, and the appended review was the only text naming a
    # verdict. It became the stored verdict, with a NULL confidence.
    analysis = """
Let me gather more evidence before concluding — I need the AgnosticV config, VM details, and recent changes.

### Model adjudication — review only
Status: needs_human_review. Human verification is still required.
Blind reviewer 2: ACTIONABLE (75% model confidence).
Blind reviewer 1 (granite-3-2-8b-instruct): validation failed (invalid_claim_citations).
Judge: disputed. Insufficient root cause evidence
No remediation was executed. Model agreement is not verified accuracy.
"""

    fields = _extract_structured_fields(analysis)

    assert fields["verdict"] is None
    # "75% model confidence" must not become the agent's own confidence either.
    assert fields["confidence"] is None


def test_verdict_section_wins_over_a_disagreeing_adjudication_summary():
    analysis = """
### 6. Verdict

> **TRANSIENT**

### Model adjudication — review only
Status: needs_human_review. Human verification is still required.
Blind reviewer 2: ACTIONABLE (75% model confidence).
Judge: disputed. Insufficient root cause evidence
"""

    assert _extract_structured_fields(analysis)["verdict"] == "TRANSIENT"


def test_judge_rationale_does_not_supply_confidence():
    analysis = """
### 2. Root Cause
The image tag is missing.

### Model adjudication — review only
Status: needs_human_review. Human verification is still required.
Judge: disputed. Confidence: 0.9 that the PVC is corrupted.
"""

    assert _extract_structured_fields(analysis)["confidence"] is None


def test_verdict_heading_after_an_earlier_lowercase_mention_is_still_found():
    # id=2945: a remediation snippet carried a YAML `verdict: complete` key,
    # which the case-insensitive heading match found first; its scope ended
    # before the real heading. The candidate that states an enum must win.
    analysis = """
### 3. Remediation Strategy

```yaml
exit_criteria:
  - name: namespace_deleted_after_pass
    verdict: complete   # suppress further evaluation
```

### 6. Verdict

> **TRANSIENT**

The namespace was reclaimed cleanly.

### 7. Confidence
"""

    assert _extract_structured_fields(analysis)["verdict"] == "TRANSIENT"


def test_bold_verdict_line_without_an_enum_does_not_shadow_the_verdict_heading():
    # id=293: "**Verdict: Watch and wait ...**" in the remediation prose matched
    # first and named no enum; the real section below still states one.
    analysis = """
### 3. Remediation Strategy

**Verdict: Watch and wait — this self-resolves in ~20 minutes.**

### 6. Verdict

**TRANSIENT** — the init container takes six minutes.

### 7. Confidence
"""

    assert _extract_structured_fields(analysis)["verdict"] == "TRANSIENT"


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
