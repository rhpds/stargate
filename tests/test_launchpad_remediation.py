"""
Suite 7: Launchpad auto-remediation E2E tests.
Validates the 3 Launchpad entries in remediations/catalog.yaml work correctly
through StarGate's execution engine.
"""
import pytest
from engine.catalog_loader import load_catalog, get_commands_for_action
from engine.models import RemediationRisk


class TestLaunchpadRemediationCatalog:

    @pytest.fixture(autouse=True)
    def catalog(self):
        self.entries = load_catalog()
        self.by_id = {e.id: e for e in self.entries}

    def test_launchpad_reclaim_session_exists(self):
        assert "launchpad_reclaim_session" in self.by_id

    def test_launchpad_release_placement_exists(self):
        assert "launchpad_release_placement" in self.by_id

    def test_launchpad_reclaim_workshop_exists(self):
        assert "launchpad_reclaim_workshop" in self.by_id

    def test_reclaim_session_is_low_risk(self):
        entry = self.by_id["launchpad_reclaim_session"]
        assert entry.risk == RemediationRisk.LOW

    def test_reclaim_workshop_is_medium_risk(self):
        entry = self.by_id["launchpad_reclaim_workshop"]
        assert entry.risk == RemediationRisk.MEDIUM

    def test_reclaim_session_auto_executes(self):
        entry = self.by_id["launchpad_reclaim_session"]
        assert entry.mode == "auto_execute"
        assert entry.requires_approval is False

    def test_forbidden_namespaces_block_openshift(self):
        entry = self.by_id["launchpad_reclaim_session"]
        assert any("openshift-*" in f for f in entry.forbidden_when)

    def test_forbidden_namespaces_block_launchpad(self):
        entry = self.by_id["launchpad_reclaim_session"]
        assert any("partner-ai-launchpad" in f for f in entry.forbidden_when)

    def test_reclaim_session_command_template_has_namespace(self):
        entry = self.by_id["launchpad_reclaim_session"]
        assert any("{namespace}" in cmd for cmd in entry.commands)

    def test_release_placement_uses_sandbox_api(self):
        entry = self.by_id["launchpad_release_placement"]
        assert entry.execution_method == "rhdp_sandbox_api"

    def test_release_placement_command_template_has_uuid(self):
        entry = self.by_id["launchpad_release_placement"]
        assert any("{placement_uuid}" in cmd for cmd in entry.commands)
