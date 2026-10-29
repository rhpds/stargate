"""Same-named failure definitions must retain source-specific evidence."""
import pytest
import yaml

from engine import failure_class_loader as loader


@pytest.fixture
def source_catalogs(tmp_path, monkeypatch):
    for filename, source in [("a.yaml", "alpha"), ("b.yaml", "beta")]:
        (tmp_path / filename).write_text(yaml.safe_dump({
            "id": source, "version": "1", "source": source,
            "classes": {"shared": {"pattern": source, "severity": "warning",
                                     "remediation": ["Review synthetic evidence"]}},
        }))
    with monkeypatch.context() as patcher:
        patcher.setattr(loader, "FAILURE_CLASSES_DIR", tmp_path)
        loader.reload()
        yield tmp_path
    loader.reload()


def test_overlapping_names_preserve_each_sources_definition(source_catalogs):
    assert loader.get_classes_by_source("alpha")["shared"]["pattern"] == "alpha"
    assert loader.get_classes_by_source("beta")["shared"]["pattern"] == "beta"
    assert loader.get_class("shared")["pattern"] == "beta"  # Existing canonical precedence.
    assert len(loader.get_all_classes()) == 1


def test_pattern_lookup_uses_requested_source(source_catalogs):
    name, definition = loader.classify_by_pattern("alpha", source="alpha")
    assert name == "shared"
    assert definition["_source"] == "alpha"
    assert definition["_source_file"] == "a.yaml"


def test_reload_drops_old_source_entries(source_catalogs):
    (source_catalogs / "b.yaml").write_text(yaml.safe_dump({
        "id": "beta", "version": "1", "source": "beta", "classes": {},
    }))
    loader.reload()
    assert loader.get_classes_by_source("beta") == {}
    assert loader.get_classes_by_source("alpha")["shared"]["pattern"] == "alpha"
