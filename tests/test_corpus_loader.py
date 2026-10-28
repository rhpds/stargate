"""Corpus loader — TDD red/green.

Runs all miners, loads classified failures into StarGate DB,
and provides API endpoints to query the corpus.
"""

import pytest


class TestCorpusRunner:
    def test_run_all_miners_exists(self):
        from engine.corpus_runner import run_all_miners
        assert callable(run_all_miners)

    def test_run_all_miners_returns_summary(self, monkeypatch):
        from unittest.mock import Mock

        from engine import alertmanager_miner, infra_miner, k8s_event_miner, prometheus_miner
        from engine.corpus_runner import run_all_miners

        sources = [(k8s_event_miner, "mine_all_clusters"),
                   (alertmanager_miner, "collect_alerts"),
                   (prometheus_miner, "mine_all_clusters"),
                   (infra_miner, "mine_all_clusters")]
        readers = []
        for module, name in sources:
            reader = Mock(return_value=[])
            monkeypatch.setattr(module, name, reader)
            readers.append(reader)
        result = run_all_miners(clusters={"synthetic": "not-used"},
                                prometheus_clusters=["synthetic"], dry_run=True)
        assert "total_findings" in result
        assert "by_source" in result
        assert "by_class" in result
        assert result["total_findings"] == 0
        assert result["errors"] == []
        for reader in readers:
            reader.assert_called_once()

    def test_corpus_stats_exists(self):
        from engine.corpus_runner import get_corpus_stats
        assert callable(get_corpus_stats)

    @pytest.mark.parametrize("definitions", [[], [
        {"name": "one", "_source": "synthetic", "severity": "warning", "remediation": ["Review"]},
        {"name": "two", "_source": "synthetic", "severity": "high", "remediation": []},
    ]])
    def test_stats_consume_loader_list_contract(self, monkeypatch, definitions):
        from engine import corpus_runner

        monkeypatch.setattr(corpus_runner, "reload", lambda: None)
        monkeypatch.setattr(corpus_runner, "get_all_classes", lambda: definitions)
        stats = corpus_runner.get_corpus_stats()
        assert stats["total_classes"] == len(definitions)
        assert sum(stats["by_source"].values()) == len(definitions)
        assert sum(stats["by_severity"].values()) == len(definitions)
        assert stats["with_remediation"] == (1 if definitions else 0)


class TestCorpusAPI:
    def test_corpus_endpoint_exists(self, client):
        response = client.get("/dashboard/corpus")
        assert response.status_code == 200
        assert response.json()["total_classes"] > 0
        assert "by_source" in response.json()
