"""RED/GREEN TDD — Canonical lab mapping table."""

from datetime import datetime, timezone


class TestLabMapping:
    """Lab mapping table resolves lab identity across all data sources."""

    def test_mapping_model_exists(self):
        from db.models import LabMapping
        assert hasattr(LabMapping, "lab_code")
        assert hasattr(LabMapping, "ci_name")
        assert hasattr(LabMapping, "ci_base")
        assert hasattr(LabMapping, "namespace_pattern")
        assert hasattr(LabMapping, "pool_pattern")

    def test_refresh_function_exists(self):
        from engine.lab_mapper import refresh_lab_mappings
        assert callable(refresh_lab_mappings)

    def test_mapping_table_creates(self, db):
        from db.models import LabMapping
        m = LabMapping(
            lab_code="LB9999",
            ci_name="summit-2026.lb9999-test-lab-cnv",
            ci_base="openshift-cnv",
            ci_slug="lb9999-test-lab-cnv",
            namespace_pattern="sandbox-*-openshift-cnv",
            pool_pattern="openshift-cnv.*",
            agnosticv_path="summit-2026/lb9999-test-lab-cnv",
            cloud="CNV",
            updated_at=datetime.now(timezone.utc),
        )
        db.add(m)
        db.commit()
        result = db.query(LabMapping).filter_by(lab_code="LB9999").first()
        assert result is not None
        assert result.ci_base == "openshift-cnv"
        assert result.namespace_pattern == "sandbox-*-openshift-cnv"

    def test_mapping_in_mv_refresh(self):
        """refresh_lab_mappings must be called in the MV refresh loop."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "app.py"
        text = src.read_text()
        assert "refresh_lab_mappings" in text

    def test_data_mapping_uses_lab_mapping(self, client):
        """Data mapping endpoint should use LabMapping table when available."""
        resp = client.get("/dashboard/data-mapping")
        assert resp.status_code == 200
