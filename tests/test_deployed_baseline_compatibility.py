"""A release must retain the migration lineage and review-only baseline."""
from pathlib import Path


def test_deployed_migration_revision_is_in_current_lineage():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    deployed = scripts.get_revision("h8c9d0e1f2a3")
    assert deployed is not None
    assert deployed.revision in {r.revision for r in scripts.walk_revisions()}
    assert deployed.revision in scripts.get_heads()


def test_review_ledger_and_bounded_query_helpers_are_available():
    from db import evaluation_queries
    from db.models import AdjudicationRecord
    from engine import memory_diagnostics

    assert AdjudicationRecord.__tablename__ == "adjudications"
    assert callable(memory_diagnostics.start_memory_diagnostics)
    assert callable(evaluation_queries.first_observed_by_lab)
    assert callable(evaluation_queries.latest_evaluations_by_pair)


def test_no_model_protocol_upgrade_is_smuggled_into_baseline_release():
    from engine.adjudication import PROTOCOL_VERSION

    assert PROTOCOL_VERSION == "adjudication-v2.5"
