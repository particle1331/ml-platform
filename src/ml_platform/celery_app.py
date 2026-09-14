"""Celery application configuration for the local experiment."""

from __future__ import annotations

import os

from celery import Celery


def _setting(name: str, default: str) -> str:
    return os.environ.get(name, default)


app = Celery(
    "ml_platform",
    broker=_setting(
        "CELERY_BROKER_URL",
        "amqp://platform:platform@localhost:5672//",
    ),
    backend=_setting(
        "CELERY_RESULT_BACKEND",
        "redis://localhost:6379/0",
    ),
    include=["ml_platform.tasks"],
)

app.conf.update(
    accept_content=["json"],
    enable_utc=True,
    result_expires=3600,
    result_serializer="json",
    task_serializer="json",
    task_send_sent_event=True,
    task_track_started=True,
    timezone="UTC",
    worker_send_task_events=True,
)
