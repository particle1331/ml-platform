"""HTTP task producer for the local Celery experiment."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from celery import Celery
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from ml_platform.constants import DEFAULT_QUEUE
from ml_platform.task_events import get_task_events

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

celery = Celery(
    "producer",
    broker=BROKER_URL,
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)
celery.conf.update(
    broker_transport_options={
        "queue_order_strategy": "priority",
        "priority_steps": list(range(10)),
    },
    task_default_queue=DEFAULT_QUEUE,
)

app = FastAPI(
    title="ML Platform Task Producer",
    openapi_tags=[
        {
            "name": "Health",
            "description": "Service health checks.",
        },
        {
            "name": "Tasks",
            "description": "Submit Celery tasks.",
        },
        {
            "name": "Results",
            "description": "Inspect task status and results.",
        },
        {
            "name": "Control",
            "description": "Inspect workers and control queued or running tasks.",
        },
    ],
)


class AddRequest(BaseModel):
    left: int
    right: int


class OneOverRequest(BaseModel):
    value: float


class WaitRequest(BaseModel):
    seconds: float = Field(ge=0, le=30)
    priority: int | None = Field(default=None, ge=0, le=9)


class SubmittedTask(BaseModel):
    task_id: str


TaskState = Literal["SUCCESS", "FAILURE", "REVOKED"]


class ActiveTask(BaseModel):
    """A Celery task currently executing on a worker."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    task: str | None = None
    worker: str | None = None
    priority: int | None = None
    redelivered: bool | None = None


class PendingTask(BaseModel):
    """The inspectable metadata of a task still queued in Redis."""

    task_id: str | None = None
    task: str | None = None
    queue: str
    args: str | None = None
    kwargs: str | None = None
    priority: int | None = None
    redelivered: bool | None = None


@app.get("/health", tags=["Health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


def _submit(
    task_name: str,
    args: list[Any],
    *,
    priority: int | None = None,
) -> SubmittedTask:
    try:
        result = celery.send_task(
            task_name,
            args=args,
            queue=DEFAULT_QUEUE,
            priority=priority,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="task broker unavailable",
        ) from exc

    return SubmittedTask(task_id=result.id)


@app.post("/tasks/add", status_code=202, response_model=SubmittedTask, tags=["Tasks"])
def submit_add(request: AddRequest) -> SubmittedTask:
    """Enqueue the allowlisted addition task."""
    return _submit("ml_platform.tasks.add", [request.left, request.right])


@app.post(
    "/tasks/one-over",
    status_code=202,
    response_model=SubmittedTask,
    tags=["Tasks"],
)
def submit_one_over(request: OneOverRequest) -> SubmittedTask:
    """Enqueue the reciprocal task."""
    return _submit("ml_platform.tasks.one_over", [request.value])


@app.post("/tasks/wait", status_code=202, response_model=SubmittedTask, tags=["Tasks"])
def submit_wait(request: WaitRequest) -> SubmittedTask:
    """Enqueue the bounded wait task."""
    return _submit(
        "ml_platform.tasks.wait",
        [request.seconds],
        priority=request.priority,
    )


_TASK_METADATA_FIELDS = (
    "name",
    "args",
    "kwargs",
    "worker",
    "retries",
    "queue",
    "date_done",
)
_TERMINAL_STATES = ("SUCCESS", "FAILURE", "REVOKED")


def _task_record(task_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Translate one Celery result into the API's task record."""
    state = meta["status"]
    record = {
        "task_id": task_id,
        "status": state,
        **{
            field: meta[field]
            for field in _TASK_METADATA_FIELDS
            if meta.get(field) is not None
        },
        **get_task_events(task_id),
    }

    if state == "SUCCESS":
        record["result"] = meta["result"]
    elif state in _TERMINAL_STATES[1:]:
        record["error"] = str(meta["result"])

    return record


def _task_matches(
    meta: dict[str, Any],
    *,
    required_states: set[str],
    name: str | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Return whether backend metadata satisfies the list query."""
    if meta.get("status") not in required_states:
        return False
    if name is not None and meta.get("name") != name:
        return False

    date_done = _parse_utc(meta.get("date_done"))
    if start and (date_done is None or date_done < start):
        return False
    if end and (date_done is None or date_done > end):
        return False
    return True


@app.get("/tasks", response_model=list[dict[str, Any]], tags=["Results"])
def task_results(
    name: str | None = None,
    task_statuses: list[TaskState] | None = Query(default=None, alias="status"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Find terminal task results stored in the Redis result backend."""
    start, end = _as_utc(start), _as_utc(end)
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start must be before end")

    required_states = set(task_statuses or _TERMINAL_STATES)
    prefix = celery.backend.task_keyprefix
    match = prefix + (b"*" if isinstance(prefix, bytes) else "*")
    results: list[dict[str, Any]] = []

    try:
        for key in celery.backend.client.scan_iter(match=match):
            task_id = key[len(prefix):].decode() if isinstance(key, bytes) else key[len(prefix):]
            meta = celery.backend.get_task_meta(task_id)
            if not _task_matches(
                meta,
                required_states=required_states,
                name=name,
                start=start,
                end=end,
            ):
                continue

            results.append(_task_record(task_id, meta))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery result backend unavailable",
        ) from exc

    results.sort(key=lambda result: result.get("date_done", ""), reverse=True)
    return results[:limit]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


@app.get("/tasks/{task_id}", tags=["Results"])
def task_status(task_id: str) -> dict[str, Any]:
    """Read the task result and worker metadata directly from Redis."""
    meta = celery.backend.get_task_meta(task_id)
    return _task_record(task_id, meta)


def _inspect_workers():
    """Create a short-lived inspector so HTTP requests do not hang indefinitely."""
    return celery.control.inspect(timeout=1.0)


def _worker_names() -> set[str]:
    try:
        workers = _inspect_workers().ping() or {}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery workers unavailable",
        ) from exc
    return set(workers)


@app.get("/active", response_model=list[ActiveTask], tags=["Control"])
def active_tasks() -> list[ActiveTask]:
    """Return tasks that workers report as currently executing."""
    try:
        active = _inspect_workers().active() or {}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery workers unavailable",
        ) from exc

    result: list[ActiveTask] = []
    for worker_tasks in active.values():
        for metadata in worker_tasks:
            normalized = dict(metadata)
            delivery_info = normalized.pop("delivery_info", {}) or {}
            normalized["task_id"] = normalized.pop("id")
            normalized["task"] = normalized.pop("name", None)
            normalized["worker"] = normalized.pop("hostname", None)
            normalized["priority"] = delivery_info.get("priority")
            normalized["redelivered"] = delivery_info.get("redelivered")
            result.append(ActiveTask.model_validate(normalized))
    return result


def _pending_task(raw: bytes, queue: str, priority: int | None) -> PendingTask:
    """Extract stable Celery headers without exposing the serialized task body."""
    message = json.loads(raw)
    headers = message.get("headers") or {}
    properties = message.get("properties") or {}
    delivery_info = properties.get("delivery_info") or {}
    return PendingTask(
        task_id=headers.get("id") or properties.get("correlation_id"),
        task=headers.get("task"),
        queue=queue,
        args=headers.get("argsrepr"),
        kwargs=headers.get("kwargsrepr"),
        priority=priority,
        redelivered=delivery_info.get("redelivered", False),
    )


@app.get("/pending", response_model=list[PendingTask], tags=["Control"])
def pending_tasks(
    queue: str = DEFAULT_QUEUE,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[PendingTask]:
    """Return task headers still waiting in the Redis broker queue."""
    try:
        pending: list[PendingTask] = []
        with celery.connection_for_read() as connection:
            with connection.channel() as channel:
                # Redis-specific Kombu internals keep priority keys in sync
                # with the broker configuration, without scanning Redis.
                for priority in channel.priority_steps:
                    key = channel._q_for_pri(queue, priority)
                    remaining = limit - len(pending)
                    messages = channel.client.lrange(key, -remaining, -1)
                    for raw in reversed(messages):
                        try:
                            pending.append(_pending_task(raw, queue, priority))
                        except (AttributeError, TypeError, ValueError):
                            continue
                    if len(pending) >= limit:
                        break
        return pending
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery broker unavailable",
        ) from exc


def _require_workers() -> None:
    if not _worker_names():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Celery workers found",
        )


@app.post("/revoke/{task_id}", tags=["Control"])
def revoke_task(task_id: str) -> dict[str, str]:
    """Ask workers to skip this task if it has not started yet."""
    _require_workers()
    try:
        celery.control.revoke(task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task revoke failed",
        ) from exc
    return {"task_id": task_id, "message": f"Task {task_id} revoke requested."}


@app.post("/abort/{task_id}", tags=["Control"])
def abort_task(task_id: str) -> dict[str, str]:
    """Ask a worker to terminate a task that is already running."""
    _require_workers()
    try:
        celery.control.revoke(task_id, terminate=True, signal="TERM")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task abort failed",
        ) from exc
    return {"task_id": task_id, "message": f"Task {task_id} abort requested."}
