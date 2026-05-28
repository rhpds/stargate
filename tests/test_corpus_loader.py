"""Corpus loader — TDD red/green.

Runs all miners, loads classified failures into StarGate DB,
and provides API endpoints to query the corpus.
"""

import pytest


class TestCorpusRunner:
    def test_run_all_miners_exists(self):
        from engine.corpus_runner import run_all_miners
        assert callable(run_all_miners)

    def test_run_all_miners_returns_summary(self):
        from engine.corpus_runner import run_all_miners
        result = run_all_miners(dry_run=True)
        assert "total_findings" in result
        assert "by_source" in result
        assert "by_class" in result

    def test_corpus_stats_exists(self):
        from engine.corpus_runner import get_corpus_stats
        assert callable(get_corpus_stats)


class TestCorpusAPI:
    def test_corpus_endpoint_exists(self):
        from api.routers.dashboard import router
        paths = [r.path for r in router.routes if hasattr(r, 'path')]
        assert "/dashboard/corpus" in paths or any("corpus" in p for p in paths)
