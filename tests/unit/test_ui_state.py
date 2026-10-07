"""Behavior of the UI's pure presentation layer."""

from datetime import datetime, timedelta, timezone

import pytest

from ml_platform import ui_state
from ml_platform.constants import TASK_REGISTRY

NOW = datetime(2026, 10, 8, 21, 0, 0, tzinfo=timezone.utc)


def record(
    task_id: str = "task-1",
    *,
    name: str = "ml_platform.tasks.add",
    status: str = "SUCCESS",
    worker: str = "celery@worker-1",
    queue: str = "default",
    date_done: datetime | None = None,
    started: datetime | None = None,
    finished: datetime | None = None,
    retries: int = 0,
    result: object = 3,
) -> dict:
    """Build a task record shaped exactly like producer._task_record."""
    item = {
        "task_id": task_id,
        "status": status,
        "name": name,
        "args": [1, 2],
        "kwargs": {},
        "worker": worker,
        "retries": retries,
        "queue": queue,
    }
    if started is not None:
        item["started"] = started.isoformat()
    if finished is not None:
        item["succeeded" if status == "SUCCESS" else "failed"] = finished.isoformat()
    done = date_done if date_done is not None else finished
    if done is not None:
        item["date_done"] = done.isoformat()
    item["result"] = result
    return item


# --- timestamps and formatting ------------------------------------------

def test_parse_timestamp_normalizes_everything_to_utc() -> None:
    assert ui_state.parse_timestamp("2026-10-08T21:00:00+00:00") == NOW
    assert ui_state.parse_timestamp("2026-10-09T05:00:00+08:00") == NOW
    # Naive timestamps are treated as UTC, never as local time.
    assert ui_state.parse_timestamp("2026-10-08T21:00:00") == NOW
    assert ui_state.parse_timestamp("not a timestamp") is None
    assert ui_state.parse_timestamp(None) is None


def test_format_age_covers_the_screenshot_granularities() -> None:
    assert ui_state.format_age(NOW, NOW) == "0s ago"
    assert ui_state.format_age(NOW - timedelta(seconds=48), NOW) == "48s ago"
    assert ui_state.format_age(NOW - timedelta(minutes=4), NOW) == "4m ago"
    assert ui_state.format_age(NOW - timedelta(hours=3), NOW) == "3h ago"
    assert ui_state.format_age(NOW - timedelta(days=15), NOW) == "15d ago"
    assert ui_state.format_age(None, NOW) == "—"


def test_format_short_age_uses_now_for_fresh_executions() -> None:
    assert ui_state.format_short_age(NOW - timedelta(seconds=30), NOW) == "now"
    assert ui_state.format_short_age(NOW - timedelta(minutes=4), NOW) == "4m"
    assert ui_state.format_short_age(NOW - timedelta(days=15), NOW) == "15d"
    assert ui_state.format_short_age(None, NOW) == "—"


def test_completion_cell_shows_age_plus_clock_in_display_timezone() -> None:
    finished = NOW - timedelta(seconds=48)  # 20:59:12 UTC = 04:59:12 Asia/Manila
    text, recent = ui_state.completion_cell(finished, NOW)
    assert text == "48s ago · 04:59:12"
    assert recent is True


def test_completion_cell_shows_date_for_rows_older_than_a_day() -> None:
    finished = datetime(2026, 9, 29, 7, 26, 49, tzinfo=timezone.utc)  # 15:26:49 Manila
    text, recent = ui_state.completion_cell(finished, NOW)
    assert text == "29 Sept · 15:26:49"
    assert recent is False


def test_completion_cell_window_start_is_included_like_spec_intervals() -> None:
    # The recent window is [now - 24h, now]: the boundary row is still recent.
    boundary = NOW - timedelta(hours=24)
    assert ui_state.completion_cell(boundary, NOW)[1] is True
    assert ui_state.completion_cell(boundary - timedelta(seconds=1), NOW)[1] is False
    assert ui_state.completion_cell(boundary + timedelta(seconds=1), NOW)[1] is True
    assert ui_state.completion_cell(None, NOW) == ("—", False)


def test_format_runtime_matches_the_table_and_card_formats() -> None:
    assert ui_state.format_runtime(0.02) == "0.02s"
    assert ui_state.format_runtime(2.5) == "2.50s"
    assert ui_state.format_runtime(65) == "1m 05.0s"
    assert ui_state.format_runtime(None) == "—"
    assert ui_state.format_average(0.012) == "12ms"
    assert ui_state.format_average(1.5) == "1.50s"
    assert ui_state.format_average(None) == "—"


# --- runtime ------------------------------------------------------------

def test_runtime_seconds_needs_both_ends_of_execution() -> None:
    started = NOW - timedelta(seconds=2)
    assert ui_state.runtime_seconds(record(started=started, finished=NOW - timedelta(seconds=1))) == pytest.approx(1.0)
    assert ui_state.runtime_seconds(record(finished=NOW)) is None
    assert ui_state.runtime_seconds(record(started=NOW)) is None


def test_runtime_seconds_rejects_clock_skew() -> None:
    started = NOW
    assert ui_state.runtime_seconds(record(started=started, finished=NOW - timedelta(seconds=5))) is None


def test_status_tone_distinguishes_outcomes() -> None:
    assert ui_state.status_tone("SUCCESS") == "success"
    assert ui_state.status_tone("FAILURE") == "failure"
    assert ui_state.status_tone("REVOKED") == "revoked"
    assert ui_state.status_tone("PENDING") == "pending"
    assert ui_state.status_tone("STARTED") == "other"


# --- filtering, sorting, pagination --------------------------------------

def test_record_matches_searches_visible_fields_case_insensitively() -> None:
    item = record(name="ml_platform.tasks.add", worker="celery@worker-1", queue="beat")
    assert ui_state.record_matches(item, "")
    assert ui_state.record_matches(item, "ADD")
    assert ui_state.record_matches(item, "worker-1")
    assert ui_state.record_matches(item, "task-1")
    assert ui_state.record_matches(item, "beat")
    assert not ui_state.record_matches(item, "one_over")


def test_filter_runs_applies_window_and_drops_rows_without_completion() -> None:
    records = [
        record("in", date_done=NOW - timedelta(hours=1)),
        record("old", date_done=NOW - timedelta(hours=48)),
        record("undated"),
    ]
    kept = ui_state.filter_runs(records, window_hours=24, now=NOW)
    assert [item["task_id"] for item in kept] == ["in"]
    kept = ui_state.filter_runs(records, window_hours=None, now=NOW)
    assert {item["task_id"] for item in kept} == {"in", "old", "undated"}


def test_paginate_reports_showing_range_and_clamps_out_of_range_pages() -> None:
    records = [record(f"task-{index}") for index in range(920)]

    first = ui_state.paginate(records, page=1, page_size=10)
    assert first.total == 920
    assert first.page_count == 92
    assert (first.first, first.last) == (1, 10)
    assert first.showing_label == "Showing 1 to 10 of 920 entries"
    assert first.page_label == "Page 1 of 92"

    # An out-of-range page clamps to the real last page instead of losing rows.
    last = ui_state.paginate(records, page=10**9, page_size=10)
    assert last.page == 92
    assert (last.first, last.last) == (911, 920)

    empty = ui_state.paginate([], page=3, page_size=10)
    assert empty.total == 0
    assert empty.page == 1
    assert empty.page_label == "Page 1 of 1"
    assert empty.first == 0


def test_sort_records_puts_missing_values_last_in_both_directions() -> None:
    records = [
        record("undated"),
        record("new", date_done=NOW),
        record("old", date_done=NOW - timedelta(days=2)),
    ]

    descending = ui_state.sort_records(records, "time", descending=True)
    assert [item["task_id"] for item in descending] == ["new", "old", "undated"]

    ascending = ui_state.sort_records(records, "time", descending=False)
    assert [item["task_id"] for item in ascending] == ["old", "new", "undated"]


def test_sort_records_breaks_ties_by_task_id_in_the_requested_direction() -> None:
    records = [record("b", date_done=NOW), record("a", date_done=NOW), record("c", date_done=NOW)]

    descending = ui_state.sort_records(records, "time", descending=True)
    assert [item["task_id"] for item in descending] == ["c", "b", "a"]

    ascending = ui_state.sort_records(records, "time", descending=False)
    assert [item["task_id"] for item in ascending] == ["a", "b", "c"]


# --- activity buckets and registry cards --------------------------------

def test_activity_buckets_keep_empty_hours_and_exclude_outside_records() -> None:
    records = [
        record("now", date_done=NOW),
        record("start", date_done=NOW - timedelta(hours=24)),
        record("too-old", date_done=NOW - timedelta(hours=25)),
        record("future", date_done=NOW + timedelta(minutes=5)),
        record("undated"),
    ]

    buckets, peak = ui_state.activity_buckets(records, NOW)

    assert len(buckets) == 24
    assert buckets[0] == 1  # exactly at the window start belongs to the first hour
    assert buckets[23] == 1  # the newest bucket may be shorter than an hour
    assert sum(buckets) == 2
    assert peak == 1
    assert buckets.count(0) == 22


def test_summarize_task_type_counts_and_averages_only_usable_samples() -> None:
    records = [
        record("ok", status="SUCCESS", started=NOW - timedelta(seconds=2), finished=NOW - timedelta(seconds=1)),
        record(
            "bad",
            status="FAILURE",
            result=ValueError("boom"),
            started=NOW - timedelta(hours=1),
            finished=NOW - timedelta(hours=1) + timedelta(seconds=3),
        ),
        record("no-runtime", status="SUCCESS", date_done=NOW - timedelta(minutes=30)),
        record("retried", status="SUCCESS", retries=2, date_done=NOW - timedelta(minutes=10)),
    ]

    summary = ui_state.summarize_task_type(records, "ml_platform.tasks.add", NOW)

    assert summary.executions == 4
    assert summary.ok == 3
    assert summary.failed == 1
    assert summary.retried == 2
    # Averaged over the two records with usable runtimes: 1s and 3s.
    assert summary.average_seconds == pytest.approx(2.0)


def test_summarize_task_type_separates_window_stats_from_last_execution() -> None:
    old = record("old", date_done=NOW - timedelta(days=15))

    summary = ui_state.summarize_task_type([old], "ml_platform.tasks.add", NOW)

    assert summary.executions == 0
    assert summary.last_execution_at == ui_state.completed_at(old)


def test_summarize_registry_includes_configured_types_without_observations() -> None:
    records = [
        record("recent", name="ml_platform.tasks.count_pending", date_done=NOW - timedelta(minutes=1)),
        record("older", name="ml_platform.tasks.add", date_done=NOW - timedelta(days=2)),
    ]

    summaries = ui_state.summarize_registry(records, NOW)

    assert [summary.name for summary in summaries] == [
        "ml_platform.tasks.count_pending",
        "ml_platform.tasks.add",
        "ml_platform.tasks.one_over",
        "ml_platform.tasks.wait",
    ]
    assert set(TASK_REGISTRY) == {summary.name for summary in summaries}
    never_ran = next(summary for summary in summaries if summary.name == "ml_platform.tasks.wait")
    assert never_ran.executions == 0
    assert never_ran.average_seconds is None
    assert never_ran.last_execution_at is None


def test_worker_completion_rate_counts_only_the_last_minute() -> None:
    records = [
        record("fresh", worker="celery@worker-1", date_done=NOW - timedelta(seconds=30)),
        record("stale", worker="celery@worker-1", date_done=NOW - timedelta(minutes=5)),
        record("other", worker="celery@worker-2", date_done=NOW - timedelta(seconds=10)),
    ]

    assert ui_state.worker_completion_rate(records, "celery@worker-1", NOW) == 1
    assert ui_state.worker_completion_rate(records, "celery@worker-2", NOW) == 1
    assert ui_state.worker_completion_rate(records, None, NOW) == 0
    assert ui_state.worker_completion_rate(records, "celery@missing", NOW) == 0
