"""HTTP data access for the observability UI.

The UI never touches Redis or Celery: it reads the producer's own HTTP API —
the same routes documented at ``/docs`` — with an asynchronous client and
bounded timeouts. Every fetch is best-effort per section so that, for example,
a failed worker inspection never erases valid task results.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

# The producer serves its own API on this address. Inside Compose the producer
# listens on 18000, so the service sets ML_PLATFORM_API_URL accordingly.
PRODUCER_API_URL = os.environ.get(
    "ML_PLATFORM_API_URL", "http://127.0.0.1:8000"
).rstrip("/")

REQUEST_TIMEOUT_SECONDS = 5.0

# Upper bound on retained results fetched per refresh. The result backend keeps
# three days of records, so this covers the whole retained window locally.
FETCH_LIMIT = 2000

WORKERS_PATH = "/workers"
TASKS_PATH = "/tasks"
ACTIVE_PATH = "/active"


@dataclass
class Snapshot:
    """One refresh of the data shown by the dashboard."""

    fetched_at: datetime
    runs: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    workers: list[dict[str, Any]] = field(default_factory=list)
    active: list[dict[str, Any]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        """True when at least one section answered on this refresh."""
        return len(self.errors) < 4


def make_client() -> httpx.AsyncClient:
    """Create the shared HTTP client with bounded timeouts."""
    return httpx.AsyncClient(
        base_url=PRODUCER_API_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


async def _get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> tuple[Any | None, str | None]:
    """GET one endpoint, returning (payload, error) instead of raising."""
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPError as exc:
        return None, f"{path}: {exc.__class__.__name__}"
    except ValueError as exc:
        return None, f"{path}: invalid response ({exc})"


async def fetch_snapshot(
    client: httpx.AsyncClient,
    *,
    now: datetime | None = None,
    failure_window_hours: int = 24,
) -> Snapshot:
    """Fetch all dashboard sections concurrently.

    Sections are independent: one failing endpoint records an error for that
    section and leaves the others intact. ``failures`` is the recent-failure
    query used by the failure panel (terminal failures within its window).
    """
    now = now or datetime.now(timezone.utc)
    window_start = datetime.fromtimestamp(
        now.timestamp() - failure_window_hours * 3600, tz=timezone.utc
    )

    runs_task = _get(client, TASKS_PATH, {"limit": FETCH_LIMIT})
    failures_task = _get(
        client,
        TASKS_PATH,
        {
            "status": "FAILURE",
            "start": window_start.isoformat(),
            "limit": FETCH_LIMIT,
        },
    )
    workers_task = _get(client, WORKERS_PATH)
    active_task = _get(client, ACTIVE_PATH)

    (runs, runs_err), (failures, failures_err), (workers, workers_err), (
        active,
        active_err,
    ) = await asyncio.gather(runs_task, failures_task, workers_task, active_task)

    snapshot = Snapshot(fetched_at=now)
    for section, payload, error in (
        ("runs", runs, runs_err),
        ("failures", failures, failures_err),
        ("workers", workers, workers_err),
        ("active", active, active_err),
    ):
        if error is not None:
            snapshot.errors[section] = error
        else:
            setattr(snapshot, section, payload or [])
    return snapshot
