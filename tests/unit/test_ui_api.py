"""The UI data layer keeps partial results when one endpoint fails."""

import asyncio

import httpx

from ml_platform import ui_api


def make_snapshot(handler, *, failure_window_hours: int = 24):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://producer.test",
        ) as client:
            return await ui_api.fetch_snapshot(
                client,
                failure_window_hours=failure_window_hours,
            )

    return asyncio.run(run())


def test_worker_failure_does_not_erase_valid_task_results() -> None:
    runs = [{"task_id": "task-1", "status": "SUCCESS", "name": "ml_platform.tasks.add"}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/workers":
            return httpx.Response(503, json={"detail": "Celery workers unavailable"})
        return httpx.Response(200, json=runs if request.url.path == "/tasks" else [])

    snapshot = make_snapshot(handler)

    assert snapshot.runs == runs
    assert "workers" in snapshot.errors
    assert snapshot.connected is True


def test_snapshot_records_failure_queries_for_the_failure_panel() -> None:
    seen: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tasks":
            params = dict(request.url.params)
            if "status" in params:
                seen["failures"] = params
                return httpx.Response(200, json=[{"task_id": "failed-1", "status": "FAILURE"}])
            seen["runs"] = params
        return httpx.Response(200, json=[])

    snapshot = make_snapshot(handler, failure_window_hours=48)

    assert seen["failures"]["status"] == "FAILURE"
    # The window start must move with the requested failure window.
    assert "start" in seen["failures"]
    assert snapshot.failures[0]["task_id"] == "failed-1"


def test_all_sections_down_means_disconnected_with_empty_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    snapshot = make_snapshot(handler)

    assert snapshot.runs == []
    assert snapshot.workers == []
    assert set(snapshot.errors) == {"runs", "failures", "workers", "active"}
    assert snapshot.connected is False


def test_invalid_json_is_reported_as_an_error_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    snapshot = make_snapshot(handler)

    assert "runs" in snapshot.errors
    assert snapshot.runs == []
