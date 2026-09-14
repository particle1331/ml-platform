# Milestone 1 notes

Record the commands actually run, observed results, explanations, and limitations here.

## Setup

- Python version:
- `uv` version:
- Docker Compose version:
- Redis broker URL: `redis://redis:6379/0`
- Redis result-backend URL: `redis://redis:6379/1`
- Flower URL:

## Local messaging decision

- Use Redis as the Celery broker and result backend for this local experiment.
- Keep broker messages in Redis database 0 and task results in database 1.
- Use Flower as the operational UI for worker and task monitoring.
- RabbitMQ is not part of the active local Compose stack.

## Checkpoints

### A — Plain job

- Commands:
- Result:
- Explanation:
- Limitations:

### D — Celery and Flower

- Commands: `docker compose up -d --force-recreate --remove-orphans`
- Result: Redis-backed task execution succeeded; `add(7, 8)` returned `15`.
- Explanation: Redis carries Celery messages and stores result metadata; Flower observes Celery events.
- Limitations: Flower's RabbitMQ-specific queue-management API is unavailable with Redis as broker.

### HTTP producer experiment

- Commands: `docker compose build worker producer`; `docker compose up -d --force-recreate producer worker flower`; `POST http://127.0.0.1:8000/tasks/add` with `{"left": 10, "right": 20}`.
- Result: HTTP 202 returned task ID `9bb2b617-fcd5-43c0-ba1e-f22aa1b4e95e`; `GET /tasks/{task_id}` returned `SUCCESS` with result `30`.
- Explanation: The FastAPI producer publishes the allowlisted task name and JSON arguments; the worker executes it and Redis stores the result.
- Limitations: This is an experimental task producer, not yet the durable PostgreSQL-backed job submission API.
