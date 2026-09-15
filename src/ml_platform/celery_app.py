"""Celery application configuration for the local experiment."""

from __future__ import annotations

import os

from celery import Celery
from kombu import Queue

from ml_platform.constants import BEAT_QUEUE, DEFAULT_QUEUE, TASK_RETENTION_SECONDS


app = Celery(
    "ml-platform",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    include=["ml_platform.tasks"],
)

app.conf.update(
    accept_content=["json"],
    broker_transport_options={
        "queue_order_strategy": "priority",
        "priority_steps": list(range(10)),
    },
    beat_schedule={
        "count-pending-every-5-minutes": {
            "task": "ml_platform.tasks.count_pending",
            "schedule": 300.0,   # seconds
            "kwargs": {"queue": DEFAULT_QUEUE},
            "options": {"queue": BEAT_QUEUE},
        }
    },
    enable_utc=True,
    result_expires=TASK_RETENTION_SECONDS,
    result_extended=True,
    result_serializer="json",
    task_serializer="json",
    task_default_queue=DEFAULT_QUEUE,
    task_queues=(Queue(DEFAULT_QUEUE), Queue(BEAT_QUEUE)),
    task_send_sent_event=True,
    task_track_started=True,
    task_acks_late=True,
    timezone="UTC",
    worker_prefetch_multiplier=1,
    worker_send_task_events=True,
    task_reject_on_worker_lost=True,
    task_create_missing_queues=False,
)
