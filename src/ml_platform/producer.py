"""HTTP task producer for the local Celery experiment."""

from __future__ import annotations

import os
from typing import Any

from celery import Celery
from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


celery = Celery(
    "producer",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
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
