"""TDD tests — Extended data contracts for new endpoints."""

from pathlib import Path


class TestContractDefinitions:
    def test_contract_count(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert len(CONTRACTS) >= 14

    def test_sandbox_api_contract_exists(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert "/dashboard/sandbox-api" in CONTRACTS

    def test_zerotouch_contract_exists(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert "/dashboard/zerotouch" in CONTRACTS

    def test_capacity_analysis_contract_exists(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert "/dashboard/capacity-analysis" in CONTRACTS

    def test_aap_contract_exists(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert "/dashboard/aap" in CONTRACTS

    def test_readiness_contract_exists(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert "/dashboard/readiness" in CONTRACTS

    def test_executive_summary_contract_exists(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert "/dashboard/executive-summary" in CONTRACTS

    def test_sandbox_api_has_required_field(self):
        from contracts.dashboard_contracts import CONTRACTS
        contract = CONTRACTS["/dashboard/sandbox-api"]
        required_names = [f.name for f in contract.fields if f.required]
        assert "api_healthy" in required_names


class TestFreshnessTracking:
    def test_all_ten_sources_tracked(self):
        from api.contracts import get_freshness
        freshness = get_freshness()
        expected = ["labagator", "babylon", "scanner", "demolition", "agnosticv", "stargate_db", "llm", "aap", "sandbox_api", "zerotouch"]
        for source in expected:
            assert source in freshness, f"Missing source: {source}"


class TestLLMPromptCoverage:
    def test_all_prompts_exist(self):
        prompts_dir = Path(__file__).parent.parent / "prompts"
        expected = ["classify.yaml", "remediation.yaml", "executive-summary.yaml", "capacity-forecast.yaml",
                     "aap-failure.yaml", "failure-interpretation.yaml", "trend-analysis.yaml"]
        for name in expected:
            assert (prompts_dir / name).exists(), f"Missing prompt: {name}"

    def test_prompt_count(self):
        prompts_dir = Path(__file__).parent.parent / "prompts"
        yaml_files = list(prompts_dir.glob("*.yaml"))
        assert len(yaml_files) >= 8
