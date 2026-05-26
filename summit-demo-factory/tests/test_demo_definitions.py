"""Demo definition validation tests — verify all definitions parse and reference valid rubrics."""

from pathlib import Path

import yaml

from api.app.models import DemoDefinition
from api.app.rubric_loader import load_rubrics_from_directory


DEMO_DIR = Path(__file__).parent.parent / "demo-definitions"
RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"


def _load_demo(name: str) -> dict:
    return yaml.safe_load((DEMO_DIR / name).read_text())


def _all_rubric_ids():
    rubrics = load_rubrics_from_directory(RUBRIC_DIR)
    return {r.stage for r in rubrics}


class TestDemoDefinitionLoading:
    def test_all_definitions_exist(self):
        expected = {"demo-simple-container.yaml", "demo-vm-lane.yaml", "demo-model-lane.yaml"}
        actual = {f.name for f in DEMO_DIR.glob("*.yaml")}
        assert expected.issubset(actual)

    def test_simple_container_parses(self):
        data = _load_demo("demo-simple-container.yaml")
        demo = DemoDefinition(**data)
        assert demo.demo_id == "demo-simple-container"
        assert len(demo.stages) == 8

    def test_vm_lane_parses(self):
        data = _load_demo("demo-vm-lane.yaml")
        demo = DemoDefinition(**data)
        assert demo.demo_id == "demo-vm-lane"
        assert len(demo.stages) >= 3

    def test_model_lane_parses(self):
        data = _load_demo("demo-model-lane.yaml")
        demo = DemoDefinition(**data)
        assert demo.demo_id == "demo-model-lane"
        assert len(demo.stages) >= 3


class TestDemoDefinitionRubricCoverage:
    def test_all_definitions_reference_valid_rubrics(self):
        rubric_ids = _all_rubric_ids()
        for demo_file in DEMO_DIR.glob("*.yaml"):
            data = yaml.safe_load(demo_file.read_text())
            for stage in data.get("stages", []):
                rubric_id = stage.get("rubric_id") or stage["stage_id"]
                assert rubric_id in rubric_ids, (
                    f"{demo_file.name}: stage '{stage['stage_id']}' references "
                    f"rubric '{rubric_id}' which does not exist"
                )

    def test_simple_container_has_run_created(self):
        data = _load_demo("demo-simple-container.yaml")
        stage_ids = [s["stage_id"] for s in data["stages"]]
        assert stage_ids[0] == "cluster-health"
        assert stage_ids[1] == "run-created"
