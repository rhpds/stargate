"""Celery tasks — TDD red/green."""

import pytest


class TestCeleryApp:
    def test_celery_app_exists(self):
        from celery_app import app
        assert app.main == "stargate"

    def test_beat_schedule_defined(self):
        from celery_app import app
        schedule = app.conf.beat_schedule
        assert "scanner-tick" in schedule
        assert "mv-refresh" in schedule
        assert "corpus-mine" in schedule

    def test_broker_url_configured(self):
        from celery_app import app
        assert "redis" in app.conf.broker_url


class TestTaskModules:
    def test_scanner_task_exists(self):
        from tasks.scanner import scanner_tick
        assert callable(scanner_tick)

    def test_maintenance_tasks_exist(self):
        from tasks.maintenance import mv_refresh, warm_caches, corpus_mine
        assert callable(mv_refresh)
        assert callable(warm_caches)
        assert callable(corpus_mine)
