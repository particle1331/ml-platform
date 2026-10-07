"""Presentation logic for the observability UI.

Everything in this module is pure: it formats and aggregates the task records
returned by the producer API. The task-record schema is the existing one from
``producer._task_record`` — ``task_id``, ``status``, ``name``, ``args``,
``kwargs``, ``worker``, ``retries``, ``queue``, ``date_done`` plus the
``sent``/``received``/``started``/``succeeded``/``failed`` lifecycle timestamps
from :mod:`ml_platform.task_events`, and ``result`` or ``error``.

No Flet imports and no I/O: widgets render these values and never calculate
counts from what happens to be visible on screen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from ml_platform.constants import TASK_REGISTRY

# Timestamps are stored as UTC ISO strings; the UI displays Asia/Manila.
DISPLAY_TIMEZONE = ZoneInfo("Asia/Manila")

ACTIVITY_BUCKETS = 24
ACTIVITY_BUCKET_SECONDS = 60 * 60
DEFAULT_PAGE_SIZE = 10
PAGE_SIZES = (10, 25, 50)

# Failure panel window presets in hours, matching the screenshot's pills.
FAILURE_WINDOWS: dict[str, int] = {"12h": 12, "1d": 24, "2d": 48, "3d": 72}

# Runs-table time-range presets in hours; None means "all retained results".
RUNS_WINDOWS: dict[str, int | None] = {
    "All retained (3 days)": None,
    "Last hour": 1,
    "Last 12h": 12,
    "Last 24h": 24,
}

SortKey = str  # one of "name", "status", "time", "runtime", "worker"


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def completed_at(record: dict[str, Any]) -> datetime | None:
    """Completion time of a terminal record (backend ``date_done``)."""
    return parse_timestamp(record.get("date_done"))


def started_at(record: dict[str, Any]) -> datetime | None:
    """Execution start recorded by the lifecycle events hash."""
    return parse_timestamp(record.get("started"))


def finished_at(record: dict[str, Any]) -> datetime | None:
    """Execution end from lifecycle events, falling back to ``date_done``."""
    return (
        parse_timestamp(record.get("succeeded"))
        or parse_timestamp(record.get("failed"))
        or completed_at(record)
    )


def runtime_seconds(record: dict[str, Any]) -> float | None:
    """Execution duration in seconds, or None when timestamps are missing.

    Both endpoints must be known and the duration must not be negative;
    observability gaps are shown as unknown rather than as zero.
    """
    start, finish = started_at(record), finished_at(record)
    if start is None or finish is None:
        return None
    duration = (finish - start).total_seconds()
    return duration if duration >= 0 else None


def format_age(value: datetime | None, now: datetime) -> str:
    """Relative age like the worker cards: "0s ago", "4m ago", "15d ago"."""
    if value is None:
        return "—"
    seconds = max(0.0, (now - value).total_seconds())
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def format_short_age(value: datetime | None, now: datetime) -> str:
    """Compact age like the registry badges: "now", "4m", "15d"."""
    if value is None:
        return "—"
    seconds = max(0.0, (now - value).total_seconds())
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def format_clock(value: datetime) -> str:
    """Time of day in the display timezone: "04:58:34"."""
    return value.astimezone(DISPLAY_TIMEZONE).strftime("%H:%M:%S")


_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")


def format_date_time(value: datetime) -> str:
    """Date and time in the display timezone: "29 Sept · 15:26:49"."""
    local = value.astimezone(DISPLAY_TIMEZONE)
    return f"{local.day} {_MONTH_ABBR[local.month - 1]} · {local.strftime('%H:%M:%S')}"


def is_recent(value: datetime, now: datetime) -> bool:
    """Recent completions (last 24h) are highlighted like the screenshot."""
    return value >= now - timedelta(hours=24)


def completion_cell(value: datetime | None, now: datetime) -> tuple[str, bool]:
    """Time-column text and whether it should use the recent (green) tone.

    Recent rows show a relative age plus the clock; older rows show the date.
    """
    if value is None:
        return "—", False
    if is_recent(value, now):
        return f"{format_age(value, now)} · {format_clock(value)}", True
    return format_date_time(value), False


def format_runtime(seconds: float | None) -> str:
    """Runtime column format: "0.02s", "1.50s", "1m 05s", or "—"."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:04.1f}s"


def format_average(seconds: float | None) -> str:
    """Average-runtime format for registry cards: "12ms", "0.85s", or "—"."""
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{round(seconds * 1000)}ms"
    return f"{seconds:.2f}s"


def status_tone(status: str) -> str:
    """Map a Celery state to the UI's status tone names."""
    return {
        "SUCCESS": "success",
        "FAILURE": "failure",
        "REVOKED": "revoked",
        "PENDING": "pending",
    }.get(status, "other")


def record_matches(record: dict[str, Any], query: str) -> bool:
    """Case-insensitive substring search over the record's visible fields."""
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        str(record.get(field) or "")
        for field in ("name", "task_id", "worker", "status", "queue")
    ).lower()
    return needle in haystack


@dataclass(frozen=True)
class PageSlice:
    """One page of an already filtered and sorted list."""

    items: list[dict[str, Any]]
    total: int
    page: int
    page_count: int
    first: int  # 1-based index of the first shown row, 0 when empty
    last: int  # 1-based index of the last shown row, 0 when empty

    @property
    def showing_label(self) -> str:
        return f"Showing {self.first} to {self.last} of {self.total} entries"

    @property
    def page_label(self) -> str:
        return f"Page {self.page} of {self.page_count}"


def paginate(
    items: Sequence[dict[str, Any]],
    page: int,
    page_size: int,
) -> PageSlice:
    """Slice a list into a page, clamping the page number into range."""
    total = len(items)
    page_count = max(1, math.ceil(total / page_size))
    page = min(max(1, page), page_count)
    start = (page - 1) * page_size
    shown = list(items[start : start + page_size])
    first = start + 1 if shown else 0
    last = start + len(shown) if shown else 0
    return PageSlice(
        items=shown,
        total=total,
        page=page,
        page_count=page_count,
        first=first,
        last=last,
    )


_SORT_FIELDS: dict[SortKey, Any] = {
    "name": lambda r: (str(r.get("name") or ""), str(r.get("task_id") or "")),
    "status": lambda r: (str(r.get("status") or ""), str(r.get("task_id") or "")),
    "worker": lambda r: (str(r.get("worker") or ""), str(r.get("task_id") or "")),
    "time": lambda r: (completed_at(r) or datetime.max.replace(tzinfo=timezone.utc), str(r.get("task_id") or "")),
    "runtime": lambda r: (runtime_seconds(r) if runtime_seconds(r) is not None else math.inf, str(r.get("task_id") or "")),
}


def sort_records(
    records: Iterable[dict[str, Any]],
    key: SortKey,
    descending: bool,
) -> list[dict[str, Any]]:
    """Sort records for display.

    Unknown values sort last in both directions (they are gaps in the data,
    not extremes), and every sort falls back to task ID so equal timestamps
    have a deterministic order.
    """
    sort_key = _SORT_FIELDS.get(key, _SORT_FIELDS["time"])

    def is_gap(record: dict[str, Any]) -> bool:
        value = sort_key(record)[0]
        return value == math.inf or _is_max_date(value)

    known = [r for r in records if not is_gap(r)]
    gaps = [r for r in records if is_gap(r)]
    known.sort(key=sort_key, reverse=descending)
    gaps.sort(key=lambda r: str(r.get("task_id") or ""))
    return known + gaps


def _is_max_date(value: Any) -> bool:
    return isinstance(value, datetime) and value.year == datetime.max.year


def filter_runs(
    records: Iterable[dict[str, Any]],
    *,
    query: str = "",
    window_hours: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Apply the runs-table search and optional completion-time window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours) if window_hours else None
    kept: list[dict[str, Any]] = []
    for record in records:
        if not record_matches(record, query):
            continue
        if cutoff is not None:
            finished = completed_at(record)
            if finished is None or finished < cutoff:
                continue
        kept.append(record)
    return kept


def activity_buckets(
    records: Iterable[dict[str, Any]],
    now: datetime,
    *,
    name: str | None = None,
) -> tuple[list[int], int]:
    """Count completions in 24 rolling one-hour buckets ending at ``now``.

    Returns the bucket counts (oldest first) and their peak. Empty buckets
    stay zero: a measured zero differs from missing history. Records outside
    the window or without a completion time are excluded.
    """
    counts = [0] * ACTIVITY_BUCKETS
    window_start = now - timedelta(seconds=ACTIVITY_BUCKETS * ACTIVITY_BUCKET_SECONDS)
    for record in records:
        if name is not None and record.get("name") != name:
            continue
        finished = completed_at(record)
        if finished is None or finished < window_start or finished > now:
            continue
        offset = int((finished - window_start).total_seconds() // ACTIVITY_BUCKET_SECONDS)
        counts[min(offset, ACTIVITY_BUCKETS - 1)] += 1
    return counts, max(counts, default=0)


@dataclass(frozen=True)
class TaskTypeSummary:
    """Registry-card statistics for one task type over the last 24 hours."""

    name: str
    executions: int
    ok: int
    failed: int
    retried: int
    average_seconds: float | None
    last_execution_at: datetime | None
    buckets: tuple[int, ...]
    peak: int


def summarize_task_type(
    records: Iterable[dict[str, Any]],
    name: str,
    now: datetime,
) -> TaskTypeSummary:
    """Aggregate one task type from the fetched records.

    Card counts cover the last 24 hours like the activity chart. The average
    runtime only averages records with usable runtime samples, and the last
    execution badge is not window-limited.
    """
    window_start = now - timedelta(hours=24)
    executions = ok = failed = retried = 0
    runtime_total = 0.0
    runtime_samples = 0
    last_execution_at: datetime | None = None

    for record in records:
        if record.get("name") != name:
            continue
        finished = completed_at(record)
        if finished is not None and (
            last_execution_at is None or finished > last_execution_at
        ):
            last_execution_at = finished
        if finished is None or finished < window_start or finished > now:
            continue
        executions += 1
        status = record.get("status")
        if status == "SUCCESS":
            ok += 1
        elif status == "FAILURE":
            failed += 1
        retried += int(record.get("retries") or 0)
        duration = runtime_seconds(record)
        if duration is not None:
            runtime_total += duration
            runtime_samples += 1

    buckets, peak = activity_buckets(records, now, name=name)
    return TaskTypeSummary(
        name=name,
        executions=executions,
        ok=ok,
        failed=failed,
        retried=retried,
        average_seconds=(runtime_total / runtime_samples) if runtime_samples else None,
        last_execution_at=last_execution_at,
        buckets=tuple(buckets),
        peak=peak,
    )


def summarize_registry(
    records: Iterable[dict[str, Any]],
    now: datetime,
    *,
    names: Sequence[str] = TASK_REGISTRY,
) -> list[TaskTypeSummary]:
    """Summarize every code-configured task type, most recent first.

    Configured types with no observations are included so the registry shows
    the platform's tasks, not just whatever happened to run lately.
    """
    summaries = [summarize_task_type(records, name, now) for name in names]
    # Name-ascending first, then a stable most-recent-first pass: ties keep
    # alphabetical order while the most recently executed type leads.
    summaries.sort(key=lambda summary: summary.name)
    summaries.sort(
        key=lambda summary: summary.last_execution_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return summaries


def worker_completion_rate(
    records: Iterable[dict[str, Any]],
    worker: str | None,
    now: datetime,
) -> int:
    """Completions by this worker in the last minute (approximate rate).

    Derived from the fetched retained results, so it is a recent-completion
    count, not a broker-level throughput measurement.
    """
    if not worker:
        return 0
    cutoff = now - timedelta(seconds=60)
    rate = 0
    for record in records:
        if record.get("worker") != worker:
            continue
        finished = completed_at(record)
        if finished is not None and cutoff <= finished <= now:
            rate += 1
    return rate
