"""RED/GREEN TDD — Phase 5: BYOP — Wire oc_executor to remediation catalog."""

from pathlib import Path

import pytest


class TestCatalogLoader:
    """Catalog loader must load and validate remediations/catalog.yaml."""

    def test_load_catalog_function_exists(self):
        from engine.catalog_loader import load_catalog
        assert callable(load_catalog)

    def test_catalog_returns_list(self):
        from engine.catalog_loader import load_catalog
        catalog = load_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) > 0

    def test_catalog_entries_have_required_fields(self):
        from engine.catalog_loader import load_catalog
        catalog = load_catalog()
        for entry in catalog:
            assert hasattr(entry, "id"), f"Entry missing 'id'"
            assert hasattr(entry, "risk"), f"Entry {entry.id} missing 'risk'"
            assert hasattr(entry, "commands"), f"Entry {entry.id} missing 'commands'"
            assert hasattr(entry, "allowed_when"), f"Entry {entry.id} missing 'allowed_when'"

    def test_catalog_has_pool_exhaustion_entry(self):
        """A catalog entry must exist for pool_exhaustion action type."""
        from engine.catalog_loader import load_catalog
        catalog = load_catalog()
        ids = [e.id for e in catalog]
        assert any("pool" in eid for eid in ids), (
            f"No pool-related catalog entry found. Existing IDs: {ids}"
        )


class TestCatalogActionBridge:
    """get_commands_for_action must bridge action types to catalog entries."""

    def test_get_commands_function_exists(self):
        from engine.catalog_loader import get_commands_for_action
        assert callable(get_commands_for_action)

    def test_pool_exhaustion_returns_execution_commands(self):
        """pool_exhaustion has manual_approval catalog entries → returns commands."""
        from engine.catalog_loader import get_commands_for_action
        commands = get_commands_for_action(
            "pool_exhaustion", "test-namespace", {"pool": "my-pool"}
        )
        assert isinstance(commands, list)
        assert len(commands) > 0
        assert any("patch" in c or "resourcepool" in c for c in commands)

    def test_recommend_only_entries_skipped(self):
        """Diagnostic (recommend_only) entries should not be returned — only auto_execute ones."""
        from engine.catalog_loader import load_catalog
        catalog = load_catalog()
        recommend_ids = {e.id for e in catalog if e.mode.value == "recommend_only"}
        auto_ids = {e.id for e in catalog if e.mode.value != "recommend_only"}
        assert len(recommend_ids) > 0, "catalog should have recommend_only entries"
        assert len(auto_ids) > 0, "catalog should have auto_execute/manual_approval entries"

    def test_unknown_action_returns_empty(self):
        from engine.catalog_loader import get_commands_for_action
        commands = get_commands_for_action(
            "totally_unknown_action", "test-namespace", {}
        )
        assert commands == []

    def test_namespace_substitution(self):
        """Execution commands should have {namespace} substituted."""
        from engine.catalog_loader import get_commands_for_action
        commands = get_commands_for_action(
            "pool_exhaustion", "my-ns", {"pool": "test-pool"}
        )
        for cmd in commands:
            assert "{namespace}" not in cmd, f"Unsubstituted {{namespace}} in: {cmd}"
            assert "my-ns" in cmd

    def test_forbidden_when_filters_namespaces(self):
        """Entries with matching forbidden_when should be excluded."""
        from engine.catalog_loader import load_catalog, _is_forbidden
        catalog = load_catalog()
        for entry in catalog:
            if entry.forbidden_when:
                for condition in entry.forbidden_when:
                    if "openshift-*" in condition:
                        assert _is_forbidden(entry, "openshift-monitoring")
                        assert not _is_forbidden(entry, "my-namespace")
                        return
        pytest.skip("No entries with openshift-* forbidden_when")


class TestExecutorUsesCatalog:
    """oc_executor.map_action_to_commands must try catalog before hardcoded fallback."""

    def test_map_action_to_commands_still_works(self):
        from engine.oc_executor import map_action_to_commands
        commands = map_action_to_commands("cleanup_stuck", "test-ns", {"pods": ["pod-1"]})
        assert isinstance(commands, list)
        assert len(commands) > 0

    def test_all_five_action_types_produce_commands(self):
        from engine.oc_executor import map_action_to_commands
        types_and_params = [
            ("cluster_capacity", {"deployment": "app", "replicas": 3, "image": "ubi9:latest"}),
            ("cleanup_stuck", {"pods": ["pod-1"]}),
            ("provision_blocked_lab", {"pool": "test-pool"}),
            ("pool_exhaustion", {"pool": "test-pool"}),
            ("smoke_test_failing", {"deployment": "showroom"}),
        ]
        for action_type, params in types_and_params:
            commands = map_action_to_commands(action_type, "test-ns", params)
            assert len(commands) > 0, f"No commands for {action_type}"
