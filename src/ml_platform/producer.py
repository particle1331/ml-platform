"""HTTP task producer for the local Celery experiment."""

from __future__ import annotations

import json
import os
from typing import Any

from celery import Celery
from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis


BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

celery = Celery(
    "producer",
    broker=BROKER_URL,
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)

app = FastAPI(title="ML Platform Task Producer")


class AddRequest(BaseModel):
    left: int
    right: int


class OneOverRequest(BaseModel):
    value: float


class WaitRequest(BaseModel):
    seconds: float = Field(ge=0, le=30)


class SubmittedTask(BaseModel):
    task_id: str
    task_name: str
    status: str = "PENDING"


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _submit(task_name: str, args: list[Any]) -> SubmittedTask:
    try:
        result = celery.send_task(task_name, args=args)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="task broker unavailable",
        ) from exc

    return SubmittedTask(task_id=result.id, task_name=task_name)


@app.post("/tasks/add", status_code=202, response_model=SubmittedTask)
def submit_add(request: AddRequest) -> SubmittedTask:
    """Enqueue the allowlisted addition task."""
    return _submit("ml_platform.tasks.add", [request.left, request.right])


@app.post("/tasks/one-over", status_code=202, response_model=SubmittedTask)
def submit_one_over(request: OneOverRequest) -> SubmittedTask:
    """Enqueue the reciprocal task."""
    return _submit("ml_platform.tasks.one_over", [request.value])


@app.post("/tasks/wait", status_code=202, response_model=SubmittedTask)
def submit_wait(request: WaitRequest) -> SubmittedTask:
    """Enqueue the bounded wait task."""
    return _submit("ml_platform.tasks.wait", [request.seconds])


@app.get("/tasks/{task_id}")
def task_status(task_id: str) -> dict[str, Any]:
    """Read task state and, when available, its small result from Redis."""
    result = AsyncResult(task_id, app=celery)
    payload: dict[str, Any] = {"task_id": task_id, "status": result.state}

    if result.ready():
        if result.successful():
            payload["result"] = result.result
        else:
            payload["error"] = str(result.result)

    return payload


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


@app.get("/active", response_model=list[ActiveTask])
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


def _pending_queue_keys(client: Redis[Any], queue: str) -> list[tuple[str, int | None]]:
    """Find the base Redis queue and Celery's priority-suffixed queues."""
    keys: list[tuple[str, int | None]] = [(queue, None)]
    prefix = f"{queue}\x06\x16"
    for key in client.scan_iter(match=f"{prefix}*"):
        key_name = key.decode() if isinstance(key, bytes) else key
        try:
            priority = int(key_name.removeprefix(prefix))
        except ValueError:
            continue
        keys.append((key_name, priority))
    return keys


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


@app.get("/pending", response_model=list[PendingTask])
def pending_tasks(
    queue: str = "celery",
    limit: int = Query(default=50, ge=1, le=500),
) -> list[PendingTask]:
    """Return task headers still waiting in the Redis broker queue."""
    client = Redis.from_url(BROKER_URL)
    try:
        pending: list[PendingTask] = []
        for queue_key, priority in _pending_queue_keys(client, queue):
            # Celery uses LPUSH/RPOP, so reverse Redis's newest-first list order.
            for raw in reversed(client.lrange(queue_key, 0, -1)):
                try:
                    pending.append(_pending_task(raw, queue, priority))
                except (TypeError, ValueError, json.JSONDecodeError):
                    # Do not make the monitoring endpoint fail because a broker
                    # message uses an unexpected protocol or serializer.
                    continue
                if len(pending) >= limit:
                    return pending
        return pending
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery broker unavailable",
        ) from exc
    finally:
        client.close()


def _require_workers() -> None:
    if not _worker_names():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Celery workers found",
        )


@app.post("/revoke/{task_id}")
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


@app.post("/abort/{task_id}")
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
