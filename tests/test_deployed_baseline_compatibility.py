"""A release must retain the migration lineage and review-only baseline."""
from pathlib import Path

# The revision running in production as of the last release. It has to stay on
# the lineage — production must never be off a branch or on rewritten history —
# but it does not have to be the head: every migration added since a release
# makes the deployed revision a parent of one. (This asserted `in get_heads()`
# until 2026-11-23, wrapping on the first migration after every deploy.)
DEPLOYED_REVISION = "r9a0b1c2d3e4"


def test_deployed_migration_revision_is_in_current_lineage():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    deployed = scripts.get_revision(DEPLOYED_REVISION)
    assert deployed is not None
    head = scripts.get_current_head()
    lineage = {r.revision for r in scripts.iterate_revisions(head, "base")}
    assert deployed.revision in lineage, (
        f"{DEPLOYED_REVISION} is no longer an ancestor of head {head}"
    )


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
