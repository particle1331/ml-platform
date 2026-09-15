import pytest

from ml_platform import producer
from ml_platform import tasks


def test_wait_returns_requested_seconds_without_sleeping_for_real(
    monkeypatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(tasks.time, "sleep", slept.append)

    result = tasks.wait.run(2.5)

    assert result == 2.5
    assert slept == [2.5]


@pytest.mark.parametrize("seconds", [-0.1, 30.1])
def test_wait_rejects_seconds_outside_allowed_range(seconds: float) -> None:
    with pytest.raises(ValueError, match="seconds must be between 0 and 30"):
        tasks.wait.run(seconds)


def test_task_status_reads_backend_meta_and_adds_lifecycle_events(monkeypatch) -> None:
    meta = {
        "status": "SUCCESS",
        "name": "ml_platform.tasks.add",
        "args": [1, 2],
        "result": 3,
        "date_done": "2026-09-15T00:00:00+00:00",
    }
    monkeypatch.setattr(producer.celery.backend, "get_task_meta", lambda task_id: meta)
    monkeypatch.setattr(
        producer,
        "get_task_events",
        lambda task_id: {"started": "2026-09-15T00:00:00+00:00"},
    )

    assert producer.task_status("task-1") == {
        "task_id": "task-1",
        "status": "SUCCESS",
        "name": "ml_platform.tasks.add",
        "args": [1, 2],
        "date_done": "2026-09-15T00:00:00+00:00",
        "started": "2026-09-15T00:00:00+00:00",
        "result": 3,
    }


def test_task_record_exposes_terminal_failures_as_errors(monkeypatch) -> None:
    monkeypatch.setattr(producer, "get_task_events", lambda task_id: {})

    record = producer._task_record(
        "task-2",
        {"status": "FAILURE", "result": ValueError("bad input")},
    )

    assert record == {
        "task_id": "task-2",
        "status": "FAILURE",
        "error": "bad input",
    }
