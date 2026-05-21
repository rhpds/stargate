"""Tests for YAML rubric loading and validation."""

import tempfile
from pathlib import Path

import pytest

from engine.rubric_loader import RubricLoadError, load_rubric, load_rubrics_from_directory


VALID_RUBRIC_YAML = """\
id: namespace-ready
version: v0.1.0
stage: namespace-ready
entry_criteria: []
exit_criteria:
  - name: namespace_exists
    required: true
outcomes:
  pass:
    when: all_required_exit_criteria_pass
  fail:
    when: any_required_exit_criteria_fail
failure_classes:
  namespace_missing:
    when:
      - namespace_exists == false
    recommended_action: create_namespace
allowed_remediations:
  - create_namespace
forbidden_remediations:
  - delete_namespace
"""

INVALID_RUBRIC_MISSING_ID = """\
version: v0.1.0
stage: namespace-ready
exit_criteria:
  - name: namespace_exists
    required: true
"""

INVALID_YAML = """\
id: test
version: v0.1.0
stage: test
exit_criteria:
  - name: [invalid nested
"""


class TestLoadRubric:
    def test_load_valid_rubric(self, tmp_path):
        path = tmp_path / "test.yaml"
        path.write_text(VALID_RUBRIC_YAML)
        rubric = load_rubric(path)
        assert rubric.id == "namespace-ready"
        assert rubric.version == "v0.1.0"
        assert len(rubric.exit_criteria) == 1
        assert rubric.exit_criteria[0].name == "namespace_exists"

    def test_load_rubric_file_not_found(self, tmp_path):
        path = tmp_path / "nonexistent.yaml"
        with pytest.raises(RubricLoadError, match="not found"):
            load_rubric(path)

    def test_load_rubric_wrong_extension(self, tmp_path):
        path = tmp_path / "test.json"
        path.write_text("{}")
        with pytest.raises(RubricLoadError, match="must be YAML"):
            load_rubric(path)

    def test_load_rubric_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(INVALID_YAML)
        with pytest.raises(RubricLoadError, match="Invalid YAML"):
            load_rubric(path)

    def test_load_rubric_missing_required_field(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(INVALID_RUBRIC_MISSING_ID)
        with pytest.raises(RubricLoadError, match="validation failed"):
            load_rubric(path)

    def test_load_rubric_empty_file(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        with pytest.raises(RubricLoadError, match="empty"):
            load_rubric(path)

    def test_load_rubric_not_a_mapping(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(RubricLoadError, match="must be a YAML mapping"):
            load_rubric(path)

    def test_load_rubric_yml_extension(self, tmp_path):
        path = tmp_path / "test.yml"
        path.write_text(VALID_RUBRIC_YAML)
        rubric = load_rubric(path)
        assert rubric.id == "namespace-ready"


class TestLoadRubricsFromDirectory:
    def test_load_directory(self, tmp_path):
        (tmp_path / "a.yaml").write_text(VALID_RUBRIC_YAML)
        rubric2 = VALID_RUBRIC_YAML.replace("namespace-ready", "deploy-ready")
        (tmp_path / "b.yaml").write_text(rubric2)

        rubrics = load_rubrics_from_directory(tmp_path)
        assert len(rubrics) == 2

    def test_load_empty_directory(self, tmp_path):
        rubrics = load_rubrics_from_directory(tmp_path)
        assert rubrics == []

    def test_load_not_a_directory(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("hello")
        with pytest.raises(RubricLoadError, match="Not a directory"):
            load_rubrics_from_directory(path)


class TestLoadActualRubrics:
    """Load the real rubric files from the project."""

    RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "rubrics" / "platform").exists(),
        reason="Rubric files not present",
    )
    def test_load_platform_rubrics(self):
        rubrics = load_rubrics_from_directory(self.RUBRIC_DIR)
        assert len(rubrics) >= 8
        ids = {r.id for r in rubrics}
        assert "run-created" in ids
        assert "namespace-ready" in ids
        assert "deployment-ready" in ids
        assert "route-ready" in ids
        assert "smoke-test-ready" in ids
