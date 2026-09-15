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

- Commit to Redis as the Celery broker and result backend for the current platform.
- Keep broker messages in Redis database 0 and task results in database 1.
- Use Flower as the operational UI for worker and task monitoring.
- RabbitMQ and Azure Service Bus are not part of the active stack.
- Treat a future broker migration as a major, explicit migration because current code
  uses Redis-specific behavior, including queue inspection and priority handling.
- Use one shared Celery/Redis deployment across environments, with environment-
  namespaced queues such as `prod-default`, `prod-beat`, `staging-default`, and
  `staging-beat`.
- Name workers with the environment suffix, for example `worker-default.prod`,
  `worker-beat.prod`, `worker-default.staging`, and `worker-beat.staging`.
- Workers must consume only queues for their configured environment; queue prefixes
  provide routing isolation without running a separate Celery server per environment.

## Task result retention

- `TASK_RETENTION_SECONDS = 259200` keeps Celery result records and task lifecycle event hashes for **three days**.
- The value is shared by Celery's `result_expires` and the lifecycle event hash TTL, so both records expire together.
- Beat runs `count_pending` every five minutes, producing up to 288 result/event records per day and 864 over the three-day window.
- Redis memory must be monitored as task volume or result size grows; expiration limits retention but does not cap the amount held during the window.

## MLflow and Azurite initialization

- `azurite-init` is a one-shot Compose service. Its only job is to wait for
  Azurite and create the `mlflow-artifacts` Blob container if it does not exist.
- After the container is created, `azurite-init` exits successfully; it is not a
  long-running application service, so `restart: "no"` is intentional.
- MLflow depends on `azurite-init` completing successfully before it starts.
- `./scripts/init_azurite.py:/scripts/init_azurite.py:ro` is a read-only host-file
  bind mount for the initializer script. It is separate from the persistent
  `azurite_data:/data` named volume that stores Azurite data.

## TODO

- Expand the Celery unit and integration tests after the platform's final task list is defined.

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

### Celery Beat experiment

- Commands: `docker compose up -d beat`; `docker compose exec -T beat sh -c 'kill -9 1'`.
- Result: Beat published `demo-add-every-30-seconds`; the worker consumed the scheduled `add(1, 1)` task. Killing Beat's main process caused Docker to restart the service with `restart: unless-stopped`.
- Explanation: Beat uses the worker image but runs as its own single process and persists its schedule at `/data/celerybeat-schedule`.
- Limitations: A manual `docker compose kill beat` leaves the service stopped by design; restart policies handle unexpected process exits, not deliberate operator stops. Flower does not provide a reliable Beat-instance count.
