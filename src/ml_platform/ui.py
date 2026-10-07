"""Flet replica of the monitoring UI, hosted by the producer at ``/ui``.

The layout follows the reference monitoring screenshots in ``docs/``: a
Dashboard tab with the workers
panel, the failed-tasks panel and the runs table, and a Tasks tab with the
task-type registry cards. Widgets render view state assembled by
:mod:`ml_platform.ui_state` from data fetched by :mod:`ml_platform.ui_api`;
they never inspect Celery or compute counts themselves.

Refresh strategy: every region that depends on fetched data is a registered
"box" (a plain container whose content is replaced), while search inputs and
other text fields are built once in :meth:`UiState.rebuild`. The five-second
polling refresh therefore never rebuilds a text field and steals its focus.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable

import flet as ft

from ml_platform import ui_api, ui_state

REFRESH_SECONDS = 5.0

# --- palette (dark theme from the screenshots) --------------------------
BG = "#0A0A0B"
NAV_BG = "#0D0D0F"
PANEL_BG = "#121214"
CARD_BG = "#141416"
INNER_BG = "#0D0D0F"
PANEL_BORDER = "#242428"
INNER_BORDER = "#1C1C20"
TEXT = "#EDEDEF"
MUTED = "#8E8E98"
DIM = "#63636C"
GREEN = "#4ADE80"
GREEN_BG = "#0E2A1C"
GREEN_BORDER = "#1C5236"
RED = "#F87171"
RED_BG = "#2A1212"
RED_BORDER = "#5B2020"
YELLOW = "#FACC15"
WORKER_TEXT = "#8FB9B1"
MONO = "monospace"

STATUS_TONES: dict[str, tuple[str, str]] = {
    "success": (GREEN, GREEN_BG),
    "failure": (RED, RED_BG),
    "revoked": (YELLOW, "#2A2410"),
    "pending": (MUTED, "#1B1B1F"),
    "other": (MUTED, "#1B1B1F"),
}

CONTENT_WIDTH = 1360
MIN_CONTENT_WIDTH = 720
CARD_WIDTH = 328
CHART_HEIGHT = 56

# Runs/failed table column geometry.
_CHECK_WIDTH = 28
_CARET_WIDTH = 24
_NAME_FLEX = 3
_STATUS_WIDTH = 110
_TIME_WIDTH = 180
_RUNTIME_WIDTH = 90
_WORKER_FLEX = 2


# --- tiny view helpers ---------------------------------------------------

def _border(color: str = PANEL_BORDER, width: float = 1) -> ft.Border:
    side = ft.BorderSide(width=width, color=color)
    return ft.Border(top=side, right=side, bottom=side, left=side)


def _padding(x: float, y: float) -> ft.Padding:
    return ft.Padding(left=x, top=y, right=x, bottom=y)


def _dot(color: str, size: float = 6) -> ft.Container:
    return ft.Container(width=size, height=size, border_radius=size, bgcolor=color)


def _text(
    value: str,
    *,
    size: float = 11,
    color: str = TEXT,
    mono: bool = False,
    bold: bool = False,
    **kwargs: Any,
) -> ft.Text:
    return ft.Text(
        value,
        size=size,
        color=color,
        font_family=MONO if mono else None,
        weight=ft.FontWeight.BOLD if bold else None,
        **kwargs,
    )


def _panel(*controls: ft.Control, spacing: float = 12) -> ft.Container:
    """A bordered section box like the screenshots' panels."""
    return ft.Container(
        bgcolor=PANEL_BG,
        border=_border(),
        border_radius=8,
        padding=_padding(16, 12),
        content=ft.Column(controls=list(controls), spacing=spacing),
    )


def _icon_button(
    icon: str,
    tooltip: str,
    on_click: Callable | None = None,
    *,
    size: float = 16,
    color: str = MUTED,
) -> ft.IconButton:
    return ft.IconButton(
        icon=icon,
        icon_size=size,
        icon_color=color,
        tooltip=tooltip,
        on_click=on_click,
        padding=_padding(4, 4),
    )


def _search_field(hint: str, value: str, on_change: Callable, width: float) -> ft.TextField:
    return ft.TextField(
        hint_text=hint,
        value=value,
        on_change=on_change,
        prefix_icon=ft.Icons.SEARCH,
        text_size=11.5,
        width=width,
        height=34,
        border_color=PANEL_BORDER,
        border_radius=6,
        border_width=1,
        filled=True,
        fill_color=CARD_BG,
        color=TEXT,
        hint_style=ft.TextStyle(color=DIM),
        cursor_color=GREEN,
        content_padding=_padding(10, 6),
    )


def _page_size_dropdown(label: str, on_select: Callable) -> ft.Dropdown:
    return ft.Dropdown(
        value=str(ui_state.DEFAULT_PAGE_SIZE),
        options=[ft.DropdownOption(key=str(size), text=str(size)) for size in ui_state.PAGE_SIZES],
        width=84,
        text_size=10,
        text_style=ft.TextStyle(color=TEXT, size=10),
        content_padding=_padding(8, 4),
        border_color=PANEL_BORDER,
        border_radius=4,
        border_width=1,
        color=TEXT,
        fill_color=CARD_BG,
        filled=True,
        on_select=on_select,
        tooltip=label,
    )


def _status_pill(status: str) -> ft.Container:
    tone = ui_state.status_tone(status)
    fg, bg = STATUS_TONES[tone]
    return ft.Container(
        content=_text(status.title(), size=10, color=fg),
        bgcolor=bg,
        border=_border(fg if tone != "other" else PANEL_BORDER),
        border_radius=5,
        padding=_padding(9, 2),
    )


def _metric(label: str, value: str, *, value_color: str = TEXT) -> ft.Container:
    return ft.Container(
        expand=True,
        content=ft.Column(
            controls=[
                _text(label, size=8.5, color=DIM),
                _text(value, size=11, color=value_color, mono=True),
            ],
            spacing=2,
        ),
    )


def _activity_chart(buckets: tuple[int, ...], *, height: float = CHART_HEIGHT) -> ft.Container:
    """24 one-hour completion bars drawn as plain containers."""
    peak = max(buckets, default=0)
    inner_height = height - 8
    bars: list[ft.Control] = []
    for count in buckets:
        bar_height = (count / peak * inner_height) if peak and count else 0
        bars.append(
            ft.Container(
                width=8,
                height=max(2.0, bar_height) if count else 0.5,
                bgcolor=GREEN if count else "#17171A",
                border_radius=1,
            )
        )
    return ft.Container(
        height=height,
        bgcolor=INNER_BG,
        border=_border(INNER_BORDER),
        border_radius=4,
        padding=_padding(6, 4),
        content=ft.Row(
            controls=bars,
            spacing=4,
            height=inner_height,
            vertical_alignment=ft.CrossAxisAlignment.END,
        ),
    )


def _chart_axis_labels() -> ft.Row:
    return ft.Row(
        controls=[
            _text("24h ago", size=8.5, color=DIM),
            _text("12h", size=8.5, color=DIM),
            _text("now", size=8.5, color=DIM),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )


# --- navigation ----------------------------------------------------------

def _connected_badge(snapshot: ui_api.Snapshot) -> ft.Container:
    connected = snapshot.connected
    color = GREEN if connected else RED
    return ft.Container(
        content=ft.Row(
            controls=[
                _dot(color, 6),
                _text("Connected" if connected else "Disconnected", size=10, color=color),
            ],
            spacing=6,
        ),
        border=_border(GREEN_BORDER if connected else RED_BORDER),
        border_radius=10,
        padding=_padding(10, 4),
    )


def _nav_content(state: "UiState") -> ft.Row:
    items: list[ft.Control] = []
    for label in ("Dashboard", "Tasks", "Workflows"):
        active = state.tab == label.lower()
        items.append(
            ft.Container(
                on_click=lambda e, label=label: state.on_tab(label.lower()),
                padding=_padding(8, 0),
                content=ft.Column(
                    controls=[
                        _text(label, size=12, color=TEXT if active else MUTED, bold=active),
                        ft.Container(
                            height=2,
                            bgcolor=TEXT if active else None,
                            margin=ft.Padding(left=0, top=6, right=0, bottom=0),
                        ),
                    ],
                    spacing=0,
                    tight=True,
                ),
            )
        )
    items.append(ft.VerticalDivider(color=INNER_BORDER, width=16))
    items.append(state.boxes["badge"])
    return ft.Row(controls=items, spacing=22, vertical_alignment=ft.CrossAxisAlignment.CENTER)


# --- runs / failures tables ---------------------------------------------

def _table_header(state: "UiState") -> ft.Row:
    def header_cell(key: str, label: str, *, width: float | None = None, expand: int | None = None) -> ft.Control:
        active = state.sort_key == key
        if not active:
            arrow = ft.Icon(ft.Icons.SWAP_VERT, size=10, color=DIM)
        else:
            arrow = ft.Icon(
                ft.Icons.ARROW_DOWNWARD if state.sort_desc else ft.Icons.ARROW_UPWARD,
                size=10,
                color=MUTED,
            )
        return ft.Container(
            content=ft.Row(
                controls=[_text(label, size=10, color=MUTED), arrow],
                spacing=4,
                tight=True,
            ),
            width=width,
            expand=expand,
            on_click=lambda e, key=key: state.on_sort(key),
            tooltip=f"Sort by {label.lower()}",
        )

    return ft.Row(
        controls=[
            ft.Container(
                width=_CHECK_WIDTH,
                content=ft.Checkbox(value=False, disabled=True, visual_density=ft.VisualDensity.COMPACT),
            ),
            ft.Container(width=_CARET_WIDTH),
            header_cell("name", "Task Name", expand=_NAME_FLEX),
            header_cell("status", "Status", width=_STATUS_WIDTH),
            header_cell("time", "Time", width=_TIME_WIDTH),
            header_cell("runtime", "Runtime", width=_RUNTIME_WIDTH),
            header_cell("worker", "Worker", expand=_WORKER_FLEX),
        ],
        spacing=8,
        height=30,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _run_row(state: "UiState", record: dict[str, Any], *, scope: str) -> ft.Column:
    task_id = str(record.get("task_id") or "")
    finished = ui_state.completed_at(record)
    time_text, recent = ui_state.completion_cell(finished, state.now)
    expanded = task_id in state.expanded
    selected = task_id in state.selected_ids(scope)
    on_select = state.on_select_row if scope == "runs" else state.on_select_failure_row

    row = ft.Row(
        controls=[
            ft.Container(
                width=_CHECK_WIDTH,
                content=ft.Checkbox(
                    value=selected,
                    on_change=on_select,
                    data=task_id,
                    visual_density=ft.VisualDensity.COMPACT,
                ),
            ),
            ft.Container(
                width=_CARET_WIDTH,
                on_click=state.on_toggle_expand,
                data=task_id,
                content=ft.Icon(
                    ft.Icons.EXPAND_LESS if expanded else ft.Icons.KEYBOARD_ARROW_RIGHT,
                    size=14,
                    color=DIM,
                ),
            ),
            ft.Container(
                expand=_NAME_FLEX,
                content=_text(
                    str(record.get("name") or "—"),
                    size=11.5,
                    mono=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=str(record.get("name") or ""),
                ),
            ),
            ft.Container(width=_STATUS_WIDTH, content=_status_pill(str(record.get("status") or "UNKNOWN"))),
            ft.Container(width=_TIME_WIDTH, content=_text(time_text, size=10.5, color=GREEN if recent else MUTED)),
            ft.Container(
                width=_RUNTIME_WIDTH,
                content=_text(
                    ui_state.format_runtime(ui_state.runtime_seconds(record)),
                    size=10.5,
                    mono=True,
                ),
            ),
            ft.Container(
                expand=_WORKER_FLEX,
                content=_text(
                    str(record.get("worker") or "—"),
                    size=10.5,
                    color=WORKER_TEXT,
                    mono=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ),
        ],
        spacing=8,
        height=34,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    parts: list[ft.Control] = [row]
    if expanded:
        parts.append(_run_detail(record))
    parts.append(ft.Divider(height=1, thickness=1, color=INNER_BORDER))
    return ft.Column(controls=parts, spacing=4)


def _detail_line(label: str, value: Any) -> ft.Row:
    return ft.Row(
        controls=[
            ft.Container(width=90, content=_text(label, size=10, color=DIM)),
            ft.Container(
                expand=True,
                content=_text(str(value), size=10, mono=True, selectable=True),
            ),
        ],
        spacing=8,
    )


def _run_detail(record: dict[str, Any]) -> ft.Container:
    """Inline expanded detail: the record exactly as the API returns it."""

    def dump(value: Any) -> str:
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)

    lines = [
        _detail_line("Task ID", record.get("task_id") or "—"),
        _detail_line("Args", dump(record.get("args"))),
        _detail_line("Kwargs", dump(record.get("kwargs"))),
    ]
    if record.get("status") == "SUCCESS":
        lines.append(_detail_line("Result", dump(record.get("result"))))
    else:
        lines.append(_detail_line("Error", record.get("error") or "—"))
    lines.extend(
        [
            _detail_line("Queue", record.get("queue") or "—"),
            _detail_line("Retries", record.get("retries") if record.get("retries") is not None else "—"),
            _detail_line("Sent", record.get("sent") or "—"),
            _detail_line("Received", record.get("received") or "—"),
            _detail_line("Started", record.get("started") or "—"),
            _detail_line("Finished", record.get("date_done") or "—"),
        ]
    )
    return ft.Container(
        bgcolor=INNER_BG,
        border=_border(INNER_BORDER),
        border_radius=6,
        padding=_padding(12, 8),
        margin=ft.Padding(left=34, top=0, right=0, bottom=4),
        content=ft.Column(controls=lines, spacing=5),
    )


def _selection_row(state: "UiState", *, scope: str) -> ft.Row:
    count = len(state.selected_ids(scope))
    clear = state.on_clear_selection

    def action(label: str) -> ft.Container:
        return ft.Container(
            content=_text(label, size=10, color=DIM),
            border=_border(INNER_BORDER),
            border_radius=4,
            padding=_padding(10, 3),
            tooltip="Rerun/review actions are not part of this replica yet.",
        )

    return ft.Row(
        controls=[
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=18, color=GREEN),
                    ft.Column(
                        controls=[
                            _text(f"{count} selected", size=11),
                            _text("Limit 100 per action", size=9, color=DIM),
                        ],
                        spacing=1,
                        tight=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(expand=True),
            action("Rerun"),
            action("Review"),
            _icon_button(ft.Icons.CLOSE, "Clear selection", lambda e: clear(scope), size=13),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _pager_box(state: "UiState", page_slice: ui_state.PageSlice, *, scope: str) -> ft.Row:
    def turn(action: str) -> None:
        if scope == "runs":
            state.runs_page = _turn_page(action, state.runs_page)
        else:
            state.failure_page = _turn_page(action, state.failure_page)
        state.refresh_data()

    return ft.Row(
        controls=[
            _icon_button(ft.Icons.FIRST_PAGE, "First page", lambda e: turn("first"), size=14),
            _icon_button(ft.Icons.KEYBOARD_ARROW_LEFT, "Previous page", lambda e: turn("prev"), size=14),
            _text(page_slice.page_label, size=10, color=MUTED),
            _icon_button(ft.Icons.KEYBOARD_ARROW_RIGHT, "Next page", lambda e: turn("next"), size=14),
            _icon_button(ft.Icons.LAST_PAGE, "Last page", lambda e: turn("last"), size=14),
        ],
        spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _count_label(page_slice: ui_state.PageSlice) -> ft.Text:
    if page_slice.total == 0:
        return _text("No tasks to display.", size=10, color=DIM)
    return _text(page_slice.showing_label, size=10, color=DIM)


def _empty_state(headline: str, subline: str) -> ft.Container:
    return ft.Container(
        alignment=ft.Alignment.CENTER,
        padding=_padding(0, 36),
        content=ft.Column(
            controls=[
                ft.Icon(ft.Icons.INFO_OUTLINE, size=26, color=DIM),
                _text(headline, size=11.5),
                _text(subline, size=10, color=DIM),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
        ),
    )


# --- dashboard sections --------------------------------------------------

def _workers_panel(state: "UiState") -> ft.Container:
    snapshot = state.snapshot
    workers = snapshot.workers
    online = len(workers)
    active_total = sum(int(worker.get("active_count") or 0) for worker in workers)

    if "workers" in snapshot.errors:
        title, subtitle, dot_color = "Workers unavailable", snapshot.errors["workers"], RED
    elif online:
        title = f"All {online} workers operational"
        subtitle = f"{online} online · {active_total} active tasks"
        dot_color = GREEN
    else:
        title, subtitle, dot_color = "No workers responding", "0 online · 0 active tasks", RED

    header = ft.Row(
        controls=[
            _icon_button(
                ft.Icons.EXPAND_LESS if state.workers_open else ft.Icons.EXPAND_MORE,
                "Toggle worker list",
                state.on_toggle_workers,
                size=14,
            ),
            _dot(dot_color),
            _text(title, size=12, bold=True),
            _text(subtitle, size=10, color=MUTED),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    if not state.workers_open or not workers:
        return _panel(header)

    return _panel(
        header,
        ft.Row(
            controls=[_dot(GREEN), _text(f"Active Workers ({online})", size=11)],
            spacing=8,
        ),
        ft.Row(controls=[_worker_card(state, worker) for worker in workers], spacing=16, wrap=True),
    )


def _worker_card(state: "UiState", worker: dict[str, Any]) -> ft.Container:
    hostname = str(worker.get("hostname") or "unknown")
    active_count = int(worker.get("active_count") or 0)
    observed = ui_state.parse_timestamp(worker.get("observed_at"))
    rate = ui_state.worker_completion_rate(state.snapshot.runs, hostname, state.now)
    return ft.Container(
        width=340,
        bgcolor=CARD_BG,
        border=_border(),
        border_radius=8,
        padding=_padding(12, 10),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(width=6, height=6, border_radius=1, bgcolor=WORKER_TEXT),
                        ft.Container(
                            expand=True,
                            content=_text(
                                hostname,
                                size=11,
                                color=WORKER_TEXT,
                                mono=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ),
                        _text(ui_state.format_age(observed, state.now), size=9.5, color=DIM),
                        ft.Icon(ft.Icons.EXPAND_MORE, size=13, color=DIM),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[_metric("Active", str(active_count)), _metric("Rate", f"{rate}/min")],
                    spacing=0,
                ),
            ],
            spacing=12,
        ),
    )


def _failed_header(state: "UiState") -> ft.Row:
    unresolved = len(state.snapshot.failures)
    return ft.Row(
        controls=[
            _icon_button(
                ft.Icons.EXPAND_LESS if state.failed_open else ft.Icons.EXPAND_MORE,
                "Toggle failure list",
                state.on_toggle_failed,
                size=14,
            ),
            _dot(GREEN if unresolved == 0 else RED),
            _text(f"Failed tasks ({state.failure_window})", size=12, bold=True),
            _text(f"{unresolved} unresolved", size=10, color=MUTED),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _failed_filter_box(state: "UiState") -> ft.Row:
    matching = [
        record for record in state.snapshot.failures if ui_state.record_matches(record, state.failure_query)
    ]
    pills = []
    for label in ui_state.FAILURE_WINDOWS:
        active = label == state.failure_window
        pills.append(
            ft.Container(
                content=_text(label, size=10, color=TEXT if active else MUTED),
                bgcolor="#232327" if active else None,
                border_radius=4,
                padding=_padding(10, 4),
                on_click=state.on_failure_window,
                data=label,
            )
        )
    return ft.Row(
        controls=[
            ft.Row(controls=pills, spacing=2),
            _text(f"{len(matching)} matching tasks" if matching else "No matching tasks", size=10, color=DIM),
        ],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _failed_body(state: "UiState") -> ft.Column:
    failures = ui_state.sort_records(
        (record for record in state.snapshot.failures if ui_state.record_matches(record, state.failure_query)),
        state.sort_key,
        state.sort_desc,
    )
    page_slice = ui_state.paginate(failures, state.failure_page, state.failure_page_size)
    state.failure_page = page_slice.page

    body: list[ft.Control] = [_selection_row(state, scope="failures"), _table_header(state)]
    if page_slice.items:
        body.extend(_run_row(state, record, scope="failures") for record in page_slice.items)
    elif failures:
        body.append(_empty_state("No tasks match the current filter.", "Clear the search to see all failures."))
    else:
        body.append(
            _empty_state(
                f"No failed tasks detected in the last {state.failure_window}",
                "New failures will appear here instantly.",
            )
        )
    return ft.Column(controls=body, spacing=6)


def _runs_toolbar_right(state: "UiState") -> ft.Row:
    active_count = len(state.snapshot.active)
    activity = ft.Row(
        controls=[
            ft.Icon(ft.Icons.BOLT, size=13, color=GREEN if active_count else DIM),
            _text(f"{active_count} running" if active_count else "No activity", size=10, color=GREEN if active_count else DIM),
        ],
        spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    live_color = MUTED if state.paused else GREEN
    live_pill = ft.Container(
        content=ft.Row(
            controls=[_dot(live_color, 6), _text("Paused" if state.paused else "Live", size=10, color=live_color)],
            spacing=6,
        ),
        border=_border(PANEL_BORDER if state.paused else GREEN_BORDER),
        border_radius=10,
        padding=_padding(10, 4),
        on_click=state.on_toggle_pause,
        tooltip="Pause or resume live refresh",
    )
    return ft.Row(controls=[activity, live_pill], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _runs_body(state: "UiState") -> ft.Column:
    runs = ui_state.filter_runs(
        state.snapshot.runs,
        query=state.runs_query,
        window_hours=ui_state.RUNS_WINDOWS[state.runs_window],
        now=state.now,
    )
    runs = ui_state.sort_records(runs, state.sort_key, state.sort_desc)
    page_slice = ui_state.paginate(runs, state.runs_page, state.runs_page_size)
    state.runs_page = page_slice.page

    body: list[ft.Control] = [_selection_row(state, scope="runs"), _table_header(state)]
    if page_slice.items:
        body.extend(_run_row(state, record, scope="runs") for record in page_slice.items)
    else:
        body.append(_empty_state("No tasks to display.", "Submit a task to see it appear here."))
    return ft.Column(controls=body, spacing=6)


def _banner(state: "UiState") -> ft.Row | None:
    errors = state.snapshot.errors
    if not errors:
        return None
    sections = ", ".join(sorted(errors))
    return ft.Row(
        controls=[
            ft.Icon(ft.Icons.WARNING_AMBER_OUTLINED, size=14, color=RED),
            _text(
                f"Partial data: {sections} unavailable — showing the last successful values.",
                size=10.5,
                color=RED,
            ),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


# --- tasks registry ------------------------------------------------------

def _type_card(state: "UiState", summary: ui_state.TaskTypeSummary) -> ft.Container:
    last = summary.last_execution_at
    recent = bool(last and ui_state.is_recent(last, state.now))
    return ft.Container(
        width=CARD_WIDTH,
        bgcolor=PANEL_BG,
        border=_border(),
        border_radius=8,
        padding=_padding(14, 12),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            expand=True,
                            content=_text(
                                summary.name,
                                size=11.5,
                                mono=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                tooltip=summary.name,
                            ),
                        ),
                        ft.Icon(ft.Icons.ACCESS_TIME, size=11, color=GREEN if recent else DIM),
                        _text(ui_state.format_short_age(last, state.now), size=10, color=GREEN if recent else MUTED),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        _text("24H ACTIVITY", size=8.5, color=MUTED),
                        _text(f"{summary.peak} peak", size=9, color=MUTED),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                _activity_chart(summary.buckets),
                _chart_axis_labels(),
                ft.Row(
                    controls=[
                        _metric("EXEC", str(summary.executions)),
                        _metric("OK", str(summary.ok), value_color=GREEN),
                        _metric("FAIL", str(summary.failed), value_color=RED),
                        _metric("RETRY", str(summary.retried), value_color=YELLOW),
                        _metric(
                            "AVG",
                            ui_state.format_average(summary.average_seconds),
                            value_color=TEXT if summary.average_seconds is not None else DIM,
                        ),
                    ],
                    spacing=0,
                ),
                ft.Row(
                    controls=[
                        ft.Container(expand=True),
                        ft.TextButton(
                            content=ft.Row(
                                controls=[_text("→", size=10, color=MUTED), _text("Details", size=10, color=MUTED)],
                                spacing=3,
                                tight=True,
                            ),
                            on_click=state.on_open_type,
                            data=summary.name,
                            style=ft.ButtonStyle(padding=_padding(6, 2)),
                        ),
                    ],
                ),
            ],
            spacing=10,
        ),
    )


def _type_detail(state: "UiState") -> ft.Container:
    name = state.type_detail or ""
    summary = ui_state.summarize_task_type(state.snapshot.runs, name, state.now)
    recent_runs = sorted(
        (record for record in state.snapshot.runs if record.get("name") == name),
        key=lambda record: ui_state.completed_at(record) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:5]

    rows = [
        ft.Row(
            controls=[
                ft.Container(width=90, content=_status_pill(str(record.get("status") or "UNKNOWN"))),
                ft.Container(
                    width=170,
                    content=_text(
                        ui_state.format_date_time(ui_state.completed_at(record) or state.now),
                        size=10,
                        color=MUTED,
                    ),
                ),
                ft.Container(
                    width=90,
                    content=_text(ui_state.format_runtime(ui_state.runtime_seconds(record)), size=10, mono=True),
                ),
                ft.Container(
                    expand=True,
                    content=_text(str(record.get("worker") or "—"), size=10, color=WORKER_TEXT, mono=True),
                ),
            ],
            spacing=8,
            height=30,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        for record in recent_runs
    ]
    return _panel(
        ft.Row(
            controls=[
                _icon_button(ft.Icons.KEYBOARD_ARROW_LEFT, "Back to registry", state.on_close_type, size=14),
                _text("Task Registry", size=11, color=MUTED),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        _text(name, size=18, mono=True, bold=True),
        _text("24-hour completion activity", size=10, color=MUTED),
        _activity_chart(summary.buckets, height=120),
        _chart_axis_labels(),
        ft.Row(
            controls=[
                _metric("EXEC", str(summary.executions)),
                _metric("OK", str(summary.ok), value_color=GREEN),
                _metric("FAIL", str(summary.failed), value_color=RED),
                _metric("RETRY", str(summary.retried), value_color=YELLOW),
                _metric("AVG", ui_state.format_average(summary.average_seconds)),
                _metric("LAST", ui_state.format_short_age(summary.last_execution_at, state.now)),
            ],
            spacing=0,
        ),
        _text("Recent executions", size=11, bold=True),
        ft.Column(controls=rows, spacing=4)
        if rows
        else _empty_state("No executions yet.", "This task type has not run in the retained window."),
    )


def _registry_cards(state: "UiState") -> ft.Row:
    query = state.registry_query.strip().lower()
    summaries = [
        summary
        for summary in ui_state.summarize_registry(state.snapshot.runs, state.now)
        if not query or query in summary.name.lower()
    ]
    return ft.Row(
        controls=[_type_card(state, summary) for summary in summaries],
        spacing=16,
        run_spacing=16,
        wrap=True,
    )


def _workflows_placeholder() -> ft.Container:
    return _panel(
        ft.Container(
            alignment=ft.Alignment.CENTER,
            padding=_padding(0, 80),
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=28, color=DIM),
                    _text("Workflows are not part of this replica.", size=13),
                    _text(
                        "The workflow editor is deferred; see docs/specs/observability-ui.md.",
                        size=11,
                        color=DIM,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
        )
    )


# --- session state and page assembly ------------------------------------

class UiState:
    """Per-browser-session view state, event handlers and dynamic boxes."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.tab = "dashboard"
        self.now = datetime.now(timezone.utc)
        self.snapshot = ui_api.Snapshot(fetched_at=self.now)
        self.paused = False
        self.closed = False
        self.client: Any = None

        # dashboard state
        self.runs_query = ""
        self.runs_window = "All retained (3 days)"
        self.failure_query = ""
        self.failure_window = "1d"
        self.runs_page = 1
        self.runs_page_size = ui_state.DEFAULT_PAGE_SIZE
        self.failure_page = 1
        self.failure_page_size = ui_state.DEFAULT_PAGE_SIZE
        self.sort_key = "time"
        self.sort_desc = True
        self.selected_runs: set[str] = set()
        self.selected_failures: set[str] = set()
        self.expanded: set[str] = set()
        self.workers_open = True
        self.failed_open = True

        # registry state
        self.registry_query = ""
        self.type_detail: str | None = None

        # Dynamic regions replaced on refresh. Text inputs are deliberately
        # not in here so polling cannot rebuild them mid-keystroke.
        self.boxes: dict[str, ft.Container] = {
            "badge": ft.Container(content=_connected_badge(self.snapshot)),
            "banner": ft.Container(visible=False),
            "workers": ft.Container(),
            "failed_header": ft.Container(),
            "failed_filter": ft.Container(),
            "failed_body": ft.Container(),
            "failed_count": ft.Container(),
            "failed_pager": ft.Container(),
            "runs_toolbar_right": ft.Container(),
            "runs_body": ft.Container(),
            "runs_count": ft.Container(),
            "runs_pager": ft.Container(),
            "cards": ft.Container(),
        }

    # -- helpers --

    def selected_ids(self, scope: str) -> set[str]:
        return self.selected_runs if scope == "runs" else self.selected_failures

    # -- events --

    def on_tab(self, tab: str) -> None:
        self.tab = tab
        self.type_detail = None
        self.rebuild()

    def on_select_row(self, event: ft.ControlEvent) -> None:
        self._toggle_selection(self.selected_runs, event)

    def on_select_failure_row(self, event: ft.ControlEvent) -> None:
        self._toggle_selection(self.selected_failures, event)

    def _toggle_selection(self, target: set[str], event: ft.ControlEvent) -> None:
        task_id = str(event.control.data or "")
        if event.control.value:
            target.add(task_id)
        else:
            target.discard(task_id)
        self.refresh_data()

    def on_clear_selection(self, scope: str) -> None:
        self.selected_ids(scope).clear()
        self.refresh_data()

    def on_toggle_expand(self, event: ft.ControlEvent) -> None:
        task_id = str(event.control.data or "")
        if task_id in self.expanded:
            self.expanded.discard(task_id)
        else:
            self.expanded.add(task_id)
        self.refresh_data()

    def on_toggle_workers(self, _event: ft.ControlEvent) -> None:
        self.workers_open = not self.workers_open
        self.refresh_data()

    def on_toggle_failed(self, _event: ft.ControlEvent) -> None:
        self.failed_open = not self.failed_open
        self.refresh_data()

    def on_toggle_pause(self, _event: ft.ControlEvent) -> None:
        self.paused = not self.paused
        self.refresh_data()

    def on_runs_query(self, event: ft.ControlEvent) -> None:
        self.runs_query = str(event.control.value or "")
        self.runs_page = 1
        self.refresh_data()

    def on_failure_query(self, event: ft.ControlEvent) -> None:
        self.failure_query = str(event.control.value or "")
        self.failure_page = 1
        self.refresh_data()

    def on_registry_query(self, event: ft.ControlEvent) -> None:
        self.registry_query = str(event.control.value or "")
        self.refresh_data()

    def on_runs_window(self, event: ft.ControlEvent) -> None:
        label = getattr(event, "data", None) or event.control.value
        if label in ui_state.RUNS_WINDOWS:
            self.runs_window = str(label)
            self.runs_page = 1
            self.refresh_data()

    def on_failure_window(self, event: ft.ControlEvent) -> None:
        label = str(event.control.data or "")
        if label in ui_state.FAILURE_WINDOWS:
            self.failure_window = label
            self.failure_page = 1
            self.refresh_data()
            self.fetch_now()

    def on_sort(self, key: str) -> None:
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = key
            self.sort_desc = True
        self.refresh_data()

    def on_page_size(self, event: ft.ControlEvent) -> None:
        self.runs_page_size = _read_page_size(event, self.runs_page_size)
        self.runs_page = 1
        self.refresh_data()

    def on_failure_page_size(self, event: ft.ControlEvent) -> None:
        self.failure_page_size = _read_page_size(event, self.failure_page_size)
        self.failure_page = 1
        self.refresh_data()

    def on_open_type(self, event: ft.ControlEvent) -> None:
        self.type_detail = str(event.control.data or "")
        self.rebuild()

    def on_close_type(self, _event: ft.ControlEvent | None = None) -> None:
        self.type_detail = None
        self.rebuild()

    # -- rendering --

    def refresh_data(self) -> None:
        """Replace the dynamic boxes from the current snapshot."""
        self.now = datetime.now(timezone.utc)
        self.boxes["badge"].content = _connected_badge(self.snapshot)
        banner = _banner(self)
        self.boxes["banner"].content = banner
        self.boxes["banner"].visible = banner is not None

        if self.tab == "dashboard":
            self.boxes["workers"].content = _workers_panel(self)
            self.boxes["failed_header"].content = _failed_header(self)
            self.boxes["failed_filter"].content = _failed_filter_box(self)
            self.boxes["failed_body"].content = (
                _failed_body(self) if self.failed_open else ft.Column(spacing=6)
            )
            self.boxes["runs_toolbar_right"].content = _runs_toolbar_right(self)
            self.boxes["runs_body"].content = _runs_body(self)
            self._refresh_footers()
        else:
            self.boxes["cards"].content = _type_detail(self) if self.type_detail else _registry_cards(self)
        self.page.update()

    def _refresh_footers(self) -> None:
        for scope in ("runs", "failures"):
            runs = ui_state.filter_runs(
                self.snapshot.runs,
                query=self.runs_query,
                window_hours=ui_state.RUNS_WINDOWS[self.runs_window],
                now=self.now,
            )
            if scope == "runs":
                slice_ = ui_state.paginate(
                    ui_state.sort_records(runs, self.sort_key, self.sort_desc),
                    self.runs_page,
                    self.runs_page_size,
                )
                self.boxes["runs_count"].content = _count_label(slice_)
                self.boxes["runs_pager"].content = _pager_box(self, slice_, scope="runs")
            else:
                failures = [
                    record
                    for record in self.snapshot.failures
                    if ui_state.record_matches(record, self.failure_query)
                ]
                slice_ = ui_state.paginate(
                    ui_state.sort_records(failures, self.sort_key, self.sort_desc),
                    self.failure_page,
                    self.failure_page_size,
                )
                self.boxes["failed_count"].content = _count_label(slice_)
                self.boxes["failed_pager"].content = _pager_box(self, slice_, scope="failures")

    def rebuild(self) -> None:
        """Assemble the page shell; called on tab changes and detail views.

        Text inputs and other non-data controls are created here and kept out
        of the refresh path so they keep focus while data updates.
        """
        self.now = datetime.now(timezone.utc)
        # Fit the centered column to the window: capped at the screenshot's
        # width, never narrower than the table's minimum.
        viewport_width = int(self.page.width or CONTENT_WIDTH + 48)
        self.content_width = min(CONTENT_WIDTH, max(MIN_CONTENT_WIDTH, viewport_width - 48))
        header = ft.Container(
            height=46,
            bgcolor=NAV_BG,
            padding=_padding(16, 0),
            border=_border(INNER_BORDER),
            content=_nav_content(self),
        )

        if self.tab == "dashboard":
            failed_panel = _panel(
                self.boxes["failed_header"],
                ft.Row(
                    controls=[
                        _search_field(
                            "Search or filter for state, worker, task and more",
                            self.failure_query,
                            self.on_failure_query,
                            380,
                        ),
                        ft.Container(expand=True),
                        self.boxes["failed_filter"],
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.boxes["failed_body"],
                ft.Row(
                    controls=[
                        self.boxes["failed_count"],
                        ft.Container(expand=True),
                        _text("Show", size=10, color=DIM),
                        _page_size_dropdown("Rows per page", self.on_failure_page_size),
                        _text("per page", size=10, color=DIM),
                        self.boxes["failed_pager"],
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                spacing=10,
            )
            runs_panel = _panel(
                ft.Row(
                    controls=[
                        _search_field(
                            "Search or filter for state, worker, task and more",
                            self.runs_query,
                            self.on_runs_query,
                            380,
                        ),
                        ft.Dropdown(
                            value=self.runs_window,
                            options=[
                                ft.DropdownOption(key=label, text=label)
                                for label in ui_state.RUNS_WINDOWS
                            ],
                            width=190,
                            text_size=11,
                            leading_icon=ft.Icons.CALENDAR_MONTH,
                            content_padding=_padding(10, 6),
                            border_color=PANEL_BORDER,
                            border_radius=6,
                            border_width=1,
                            color=TEXT,
                            fill_color=CARD_BG,
                            filled=True,
                            on_select=self.on_runs_window,
                        ),
                        ft.Container(expand=True),
                        self.boxes["runs_toolbar_right"],
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.boxes["runs_body"],
                ft.Row(
                    controls=[
                        self.boxes["runs_count"],
                        ft.Container(expand=True),
                        _text("Show", size=10, color=DIM),
                        _page_size_dropdown("Rows per page", self.on_page_size),
                        _text("per page", size=10, color=DIM),
                        self.boxes["runs_pager"],
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                spacing=10,
            )
            body = ft.Column(
                controls=[
                    self.boxes["banner"],
                    self.boxes["workers"],
                    failed_panel,
                    runs_panel,
                ],
                spacing=14,
            )
        elif self.tab == "tasks":
            body = ft.Column(
                controls=[
                    _text("Task Registry", size=26, bold=True),
                    _text("Monitor and manage your Celery tasks", size=13, color=MUTED),
                    ft.Row(
                        controls=[
                            _search_field("Search tasks...", self.registry_query, self.on_registry_query, 620),
                            ft.Container(expand=True),
                            ft.Dropdown(
                                value="All Tags",
                                options=[ft.DropdownOption(key="All Tags", text="All Tags")],
                                width=150,
                                text_size=11,
                                leading_icon=ft.Icons.FILTER_ALT,
                                content_padding=_padding(10, 6),
                                border_color=PANEL_BORDER,
                                border_radius=6,
                                border_width=1,
                                color=TEXT,
                                fill_color=CARD_BG,
                                filled=True,
                                disabled=True,
                                tooltip="Tags are not part of the current task-record schema.",
                            ),
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.boxes["cards"],
                ],
                spacing=14,
            )
        else:
            body = _workflows_placeholder()

        # Vertical scrolling lives in a Column: a Row's scroll is horizontal
        # only and would clip everything below the fold.
        content = ft.Column(
            controls=[ft.Column(controls=[body], width=self.content_width, spacing=14)],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.page.clean()
        self.page.add(header, content)
        self.refresh_data()

    def fetch_now(self) -> None:
        """Trigger one immediate refresh from a sync event handler."""
        if self.client is not None and not self.closed:
            self.page.run_task(self._refresh_once)

    async def _refresh_once(self) -> None:
        if self.client is None:
            return
        self.snapshot = await ui_api.fetch_snapshot(
            self.client,
            failure_window_hours=ui_state.FAILURE_WINDOWS[self.failure_window],
        )
        self.refresh_data()


def _turn_page(action: str, current: int) -> int:
    return {
        "first": 1,
        "prev": current - 1,
        "next": current + 1,
        "last": 10**9,  # paginate() clamps into range and the state is updated
    }[action]


def _read_page_size(event: ft.ControlEvent, current: int) -> int:
    raw = getattr(event, "data", None) or event.control.value
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return current
    return size if size in ui_state.PAGE_SIZES else current


def main(page: ft.Page) -> None:
    """Entry point mounted at ``/ui`` by the producer."""
    page.title = "ML Platform · Monitoring"
    page.bgcolor = BG
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK

    state = UiState(page)
    page.on_disconnect = lambda _event: setattr(state, "closed", True)
    page.on_resize = lambda _event: state.rebuild()
    state.rebuild()

    async def _poll_loop() -> None:
        async with ui_api.make_client() as client:
            state.client = client
            while not state.closed:
                if not state.paused:
                    state.snapshot = await ui_api.fetch_snapshot(
                        client,
                        failure_window_hours=ui_state.FAILURE_WINDOWS[state.failure_window],
                    )
                    state.refresh_data()
                await asyncio.sleep(REFRESH_SECONDS)

    page.run_task(_poll_loop)
