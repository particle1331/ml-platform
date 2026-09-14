"""Celery application configuration for the local experiment."""

from __future__ import annotations

import os

from celery import Celery


app = Celery(
    "ml_platform",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
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
