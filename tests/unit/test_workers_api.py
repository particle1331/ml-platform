"""Behavior of the additive GET /workers control route."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from ml_platform import producer


class FakeInspector:
    """Stand-in for celery.control.inspect with scripted replies."""

    def __init__(self, ping: dict | None = None, active: dict | None = None, raises: bool = False):
        self._ping = ping or {}
        self._active = active or {}
        self._raises = raises

    def ping(self):
        if self._raises:
            raise ConnectionError("broker gone")
        return self._ping

    def active(self):
        if self._raises:
            raise ConnectionError("broker gone")
        return self._active


def test_workers_lists_idle_and_busy_workers(monkeypatch) -> None:
    monkeypatch.setattr(
        producer,
        "_inspect_workers",
        lambda: FakeInspector(
            ping={"celery@worker-1": {"ok": 1}, "celery@worker-2": {"ok": 1}},
            active={"celery@worker-1": [{"id": "a"}, {"id": "b"}], "celery@worker-2": []},
        ),
    )

    result = producer.workers()

    assert [worker.hostname for worker in result] == ["celery@worker-1", "celery@worker-2"]
    assert [worker.active_count for worker in result] == [2, 0]
    assert all(worker.status == "online" for worker in result)
    assert all(isinstance(worker.observed_at, datetime) for worker in result)
    assert all(worker.observed_at.tzinfo is not None for worker in result)


def test_idle_worker_still_appears_with_zero_active(monkeypatch) -> None:
    monkeypatch.setattr(
        producer,
        "_inspect_workers",
        lambda: FakeInspector(ping={"celery@idle": {"ok": 1}}, active={}),
    )

    result = producer.workers()

    assert len(result) == 1
    assert result[0].hostname == "celery@idle"
    assert result[0].active_count == 0


def test_workers_reports_unavailable_inspection_as_503(monkeypatch) -> None:
    monkeypatch.setattr(producer, "_inspect_workers", lambda: FakeInspector(raises=True))

    with pytest.raises(HTTPException) as excinfo:
        producer.workers()

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Celery workers unavailable"


def test_no_reply_means_no_workers_not_an_error(monkeypatch) -> None:
    monkeypatch.setattr(producer, "_inspect_workers", lambda: FakeInspector(ping={}, active={}))

    assert producer.workers() == []


def test_observed_at_is_recent_utc(monkeypatch) -> None:
    monkeypatch.setattr(
        producer,
        "_inspect_workers",
        lambda: FakeInspector(ping={"celery@worker-1": {"ok": 1}}),
    )

    before = datetime.now(timezone.utc)
    result = producer.workers()

    assert before <= result[0].observed_at <= datetime.now(timezone.utc)
