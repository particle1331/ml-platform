"""Persist task lifecycle timestamps independently of Flower.

Each task has one Redis hash, for example::

    ml-platform:task-events:<task_id>
        sent       -> <UTC timestamp>
        received   -> <UTC timestamp>
        started    -> <UTC timestamp>
        succeeded  -> <UTC timestamp>

Every signal handler updates one field on that same hash. Redis ``HSET``
changes the selected field and keeps the other event fields, so the hash
builds up the lifecycle of one task as the task moves through the system.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from celery.signals import after_task_publish, task_postrun, task_prerun, task_received
from redis import Redis

from ml_platform.constants import TASK_RETENTION_SECONDS

logger = logging.getLogger(__name__)
EVENT_KEY_PREFIX = "ml-platform:task-events:"


def _redis() -> Redis:
    return Redis.from_url(
        os.environ.get(
            "CELERY_RESULT_BACKEND",
            "redis://localhost:6379/1",
        )
    )


def _record(task_id: str | None, field: str) -> None:
    """Update one event field in the task's shared lifecycle hash."""
    if not task_id:
        return

    client = _redis()
    try:
        event_key = f"{EVENT_KEY_PREFIX}{task_id}"
        client.hset(
            event_key,
            field,
            datetime.now(timezone.utc).isoformat(),
        )
        client.expire(event_key, TASK_RETENTION_SECONDS)
    except Exception:
        # Observability must not change task execution behavior.
        logger.exception("Could not record task %s event %s", task_id, field)
    finally:
        client.close()


def get_task_events(task_id: str) -> dict[str, str]:
    """Return lifecycle timestamps recorded for a task."""
    client = _redis()
    try:
        events = client.hgetall(f"{EVENT_KEY_PREFIX}{task_id}")
        return {
            key.decode() if isinstance(key, bytes) else key:
            value.decode() if isinstance(value, bytes) else value
            for key, value in events.items()
        }
    except Exception:
        logger.exception("Could not read task events for %s", task_id)
        return {}
    finally:
        client.close()


@after_task_publish.connect
def record_sent(headers: dict[str, Any] | None = None, **_: Any) -> None:
    """Record the point at which a task was published to the broker."""
    _record((headers or {}).get("id"), "sent")


@task_received.connect
def record_received(request: Any = None, **_: Any) -> None:
    """Record the point at which a worker received a task message."""
    _record(getattr(request, "id", None), "received")


@task_prerun.connect
def record_started(task_id: str | None = None, **_: Any) -> None:
    """Record the point immediately before task execution."""
    _record(task_id, "started")


@task_postrun.connect
def record_finished(
    task_id: str | None = None,
    state: str | None = None,
    **_: Any,
) -> None:
    """Record the terminal lifecycle timestamp when execution completes."""
    if state == "SUCCESS":
        _record(task_id, "succeeded")
    elif state == "FAILURE":
        _record(task_id, "failed")
