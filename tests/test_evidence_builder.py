"""TDD tests — Shared evidence builder for consistent LLM context bundles."""


class TestEvidenceBuilder:
    def test_build_evidence_function_exists(self):
        from engine.evidence_builder import build_evidence
        assert callable(build_evidence)

    def test_empty_sections(self):
        from engine.evidence_builder import build_evidence
        result = build_evidence([])
        assert result == ""

    def test_cluster_state_section(self):
        from engine.evidence_builder import build_evidence
        result = build_evidence(["cluster_state"])
        assert isinstance(result, str)

    def test_multiple_sections(self):
        from engine.evidence_builder import build_evidence
        result = build_evidence(["cluster_state", "aap_summary", "sandbox_api"])
        assert isinstance(result, str)

    def test_invalid_section_ignored(self):
        from engine.evidence_builder import build_evidence
        result = build_evidence(["nonexistent_section", "cluster_state"])
        assert isinstance(result, str)

    def test_all_sections_available(self):
        from engine.evidence_builder import build_evidence
        all_sections = [
            "cluster_state", "pool_state", "aap_summary", "sandbox_api",
            "session_schedule", "workload_complexity", "pool_velocity",
            "readiness_gates", "top_failures",
        ]
        result = build_evidence(all_sections)
        assert isinstance(result, str)

    def test_lab_scoped_evidence(self):
        from engine.evidence_builder import build_evidence
        result = build_evidence(["cluster_state", "pool_state", "aap_summary"], lab_code="LB1208")
        assert isinstance(result, str)

    def test_cluster_scoped_evidence(self):
        from engine.evidence_builder import build_evidence
        result = build_evidence(["cluster_state"], cluster_name="ocpv05")
        assert isinstance(result, str)


class TestEvidenceConsistency:
    def test_all_llm_prompts_have_evidence_placeholder(self):
        import yaml
        from pathlib import Path
        prompts_dir = Path(__file__).parent.parent / "prompts"
        for p in prompts_dir.glob("*.yaml"):
            data = yaml.safe_load(p.read_text())
            if data.get("user_template"):
                assert "{evidence}" in data["user_template"], f"{p.name} missing {{evidence}} placeholder"

    def test_nine_prompts_exist(self):
        from pathlib import Path
        prompts_dir = Path(__file__).parent.parent / "prompts"
        yaml_files = list(prompts_dir.glob("*.yaml"))
        assert len(yaml_files) >= 9, f"Expected >= 9 prompts, found {len(yaml_files)}"
