"""Celery application for StarGate background task processing.

Replaces daemon threads with persistent, retryable, observable tasks.
Broker: Redis in ecosystem-redis namespace.
"""

import os

from celery import Celery

REDIS_URL = os.environ.get(
    "CELERY_BROKER_URL",
    "redis://:ecosystem-redis-2026@redis.ecosystem-redis.svc:6379/0",
)

app = Celery("stargate", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=100,
)

app.conf.beat_schedule = {
    "scanner-tick": {
        "task": "tasks.scanner.scanner_tick",
        "schedule": 60.0,
    },
    "mv-refresh": {
        "task": "tasks.maintenance.mv_refresh",
        "schedule": 60.0,
    },
    "corpus-mine": {
        "task": "tasks.maintenance.corpus_mine",
        "schedule": 1800.0,
    },
    "warm-caches": {
        "task": "tasks.maintenance.warm_caches",
        "schedule": 120.0,
    },
    "scan-history-write": {
        "task": "tasks.scanner.write_scan_history",
        "schedule": 300.0,
    },
}

app.autodiscover_tasks(["tasks"])
