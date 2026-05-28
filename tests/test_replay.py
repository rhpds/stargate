"""Event replay — TDD."""
import pytest


class TestReplay:
    def test_consume_exists(self):
        from cli.replay import consume_topic
        assert callable(consume_topic)

    def test_record_exists(self):
        from cli.replay import record_to_file
        assert callable(record_to_file)

    def test_playback_exists(self):
        from cli.replay import playback_from_file
        assert callable(playback_from_file)

    def test_list_topics_exists(self):
        from cli.replay import list_topics
        assert callable(list_topics)

    def test_topics_defined(self):
        from cli.replay import TOPICS
        assert "audit-trail" in TOPICS
        assert "stargate-evaluations" in TOPICS
        assert "deepfield-signals" in TOPICS
        assert len(TOPICS) == 9
