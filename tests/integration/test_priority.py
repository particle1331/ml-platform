from __future__ import annotations

import time
from typing import Any

from ml_platform.constants import DEFAULT_QUEUE
from ml_platform.producer import celery


def _wait_for_active(task_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = celery.control.inspect(timeout=1.0).active() or {}
        if any(
            task["id"] == task_id
            for worker_tasks in active.values()
            for task in worker_tasks
        ):
            return
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} was not observed as active")


def _wait_for_result(task_id: str, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        meta = celery.backend.get_task_meta(task_id)
        if meta["status"] in {"SUCCESS", "FAILURE", "REVOKED"}:
            return meta
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} did not finish")


def test_redis_priority_completes_high_priority_task_first() -> None:
    """A busy single-concurrency worker should choose priority 0 before 9."""
    blocker = celery.send_task(
        "ml_platform.tasks.wait",
        args=[3.0],
        queue=DEFAULT_QUEUE,
        priority=5,
    )
    _wait_for_active(blocker.id)

    low_priority = celery.send_task(
        "ml_platform.tasks.wait",
        args=[0.2],
        queue=DEFAULT_QUEUE,
        priority=9,
    )
    high_priority = celery.send_task(
        "ml_platform.tasks.wait",
        args=[0.0],
        queue=DEFAULT_QUEUE,
        priority=0,
    )

    _wait_for_result(blocker.id)
    high_meta = _wait_for_result(high_priority.id)
    low_meta = _wait_for_result(low_priority.id)

    assert high_meta["status"] == "SUCCESS"
    assert low_meta["status"] == "SUCCESS"
    assert high_meta["date_done"] < low_meta["date_done"]
