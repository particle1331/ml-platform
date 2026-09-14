"""Small tasks used to verify Celery, Redis, RabbitMQ, and Flower."""

from __future__ import annotations

import time

from . import task_events  # noqa: F401  # Register Celery lifecycle handlers.
from .celery_app import app
from .constants import DEFAULT_QUEUE


@app.task(name="ml_platform.tasks.add")
def add(left: int, right: int) -> int:
    """Return the sum of two integers."""
    return left + right

@app.task(name="ml_platform.tasks.one_over")
def one_over(value: float) -> float:
    """Return one divided by the supplied value."""
    if value == 0:
        raise ValueError("value must not be zero")
    return 1 / value


@app.task(name="ml_platform.tasks.wait")
def wait(seconds: float) -> float:
    """Wait briefly so the task can be observed in Flower."""
    if not 0 <= seconds <= 30:
        raise ValueError("seconds must be between 0 and 30")
    time.sleep(seconds)
    return seconds

@app.task(name="ml_platform.tasks.count_pending")
def count_pending(queue: str = DEFAULT_QUEUE) -> int:
    """Count broker-queued tasks, excluding tasks reserved or running on workers."""
    with app.connection_for_read() as connection:
        with connection.channel() as channel:
            # Redis removes the list when its last message is consumed. A
            # normal declaration makes an absent queue equivalent to empty.
            return channel.queue_declare(queue=queue).message_count
