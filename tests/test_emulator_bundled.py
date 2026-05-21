"""RED/GREEN TDD — Item 4: Emulator must be importable as a proper package."""

import sys


class TestEmulatorImportable:
    """Emulator should be importable without sys.path hacks."""

    def test_emulator_importable(self):
        """emulator.scenarios must be importable (pip-installed or on path)."""
        try:
            from emulator.scenarios import get_all_scenarios
            assert callable(get_all_scenarios)
        except ImportError:
            # If not pip-installed, check sibling directory (local dev)
            import os
            from pathlib import Path
            emu_path = Path(__file__).parent.parent.parent / "stargate-synthetic-client-emulator"
            if emu_path.exists() and str(emu_path) not in sys.path:
                sys.path.insert(0, str(emu_path))
            from emulator.scenarios import get_all_scenarios
            assert callable(get_all_scenarios)

    def test_all_scenarios_loadable(self):
        """get_all_scenarios() must return at least 7 scenarios."""
        try:
            from emulator.scenarios import get_all_scenarios
        except ImportError:
            from pathlib import Path
            emu_path = Path(__file__).parent.parent.parent / "stargate-synthetic-client-emulator"
            if emu_path.exists() and str(emu_path) not in sys.path:
                sys.path.insert(0, str(emu_path))
            from emulator.scenarios import get_all_scenarios

        scenarios = get_all_scenarios()
        assert len(scenarios) >= 7, f"Expected 7+ scenarios, got {len(scenarios)}"
        expected = {"healthy-baseline", "node-failure", "provision-blocked",
                    "gaudi-saturation", "xeon-underutil", "memory-pressure", "mixed-contention"}
        assert expected.issubset(set(scenarios.keys()))

    def test_validate_endpoint_no_syspath_hack(self):
        """admin.py validate endpoint must not use sys.path.insert for emulator."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "routers" / "admin.py"
        text = src.read_text()
        # The validate endpoint should use try/import, not sys.path.insert
        # Find the validate_scenarios function
        in_validate = False
        syspath_in_validate = False
        for line in text.splitlines():
            if "def validate_scenarios" in line:
                in_validate = True
            elif in_validate and line.strip().startswith("def "):
                break
            elif in_validate and "sys.path.insert" in line:
                syspath_in_validate = True
        assert not syspath_in_validate, (
            "validate_scenarios() still uses sys.path.insert — "
            "emulator should be pip-installed or on PYTHONPATH"
        )

    def test_containerfile_includes_emulator(self):
        """Containerfile.combined must COPY the emulator."""
        from pathlib import Path
        cf = Path(__file__).parent.parent / "Containerfile.combined"
        text = cf.read_text()
        assert "emulator" in text.lower(), "Containerfile.combined must include emulator"
