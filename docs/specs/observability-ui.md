# Flet observability UI and results API

[Architecture and milestone sequence](README.md) · [Build worksheets](../worksheets/README.md)

**Status: proposed specification, grounded in the current Redis experiment.** This document specifies documentation targets, not implemented features or completed checkpoints. It follows the supplied monitoring screenshots without importing their environment management, workflow editor, or configuration UI.

## 1. Outcome and scope

Open `http://localhost:8000/ui/` on the producer server, select an environment, find a failed execution, inspect its inputs, error and traceback, and request a new execution with the same inputs. See the new execution linked to the original. Switch to Task types to understand which functions are failing, or Monitoring to inspect activity over time.

The first implementation checkpoint should extend and test the existing results query and task detail. Build the read-only UI before enabling retry.

| Included | Deferred |
| --- | --- |
| Code-configured environment selector | Environment creation/editing, session-management API |
| Runs table, worker summary, prominent failures, details | Worker administration, queue purge, bulk retry, workflow graphs |
| Per-task-type summaries and failure drill-down | Editable task registry, tags, manual failure resolution |
| Fixed monitoring panels extended in Python | Grafana-style panel editor, arbitrary query language, alerting |
| Explicit retry of one eligible failed execution | Parameter editing, retry of successful tasks, automatic recovery |
| Recent Redis-backed observations | Long-term metrics/history and durable orchestration |

Keep the milestone 1 minimum: table, active/outcome counts, and a 24-hour outcome histogram. Introduce the richer views as bounded extensions of that dashboard, not prerequisites for its first checkpoint. Schedule, batch and registry workflows remain milestone 4 work.

### What exists today

Reviewed: `producer.py`, `task_events.py`, `celery_app.py`, `constants.py`, Compose, and milestone 1's worksheet and notes.

| Current behavior | Change needed |
| --- | --- |
| `GET /tasks?status=FAILURE` already returns failures across **all names**; `name` is optional | Use it now; no dedicated recent-failures endpoint needed |
| `/tasks` scans Redis result keys, selects terminal states, sorts by `date_done` descending and applies `limit` | Pagination, ordering, broader state coverage, explicit query metadata |
| `/tasks/{task_id}` returns result/error and selected metadata | Add traceback, environment, retry links and typed fields |
| `_task_payload()` drops backend `traceback` | Expose retained traceback on detail; verify a real failure |
| `/active` inspects executing tasks; `/pending` reads Redis queues | Neither is a complete historical catalog or an idle-worker list |
| Signal hashes retain latest sent/received/started/finished timestamps | Add submission metadata and state observations; these hashes are not attempt history |
| Results and event hashes have three-day TTLs | Label coverage; their expiration is not necessarily simultaneous because writes occur at different times |
| Notes select shared Redis and environment-prefixed queues | Actual constants/Compose still use `default` and `beat`; environment routing is not implemented |
| No Flet dependency, task-type aggregates, or manual retry endpoint | New bounded modules below |

The older architecture/worksheet describes a PostgreSQL job catalog, outbox and different broker/backend choices. This proposal starts from the implemented Redis producer and the decisions in the notes; it does not claim those durable mechanisms exist or replace the overall milestone sequence.

## 2. Hosting and UI structure

Mount a dynamic Flet app at `/ui` inside `ml_platform.producer:app`. Keep the producer's port 8000, API routes, `/docs`, `/openapi.json`, and `/health`. Use one producer container/process initially. The UI has no broker or Redis credentials in the browser.

Flet's Python UI calls the producer's HTTP results/control API with an asynchronous client and bounded timeouts. Routes own validation; a shared query service owns reading and aggregation. Widgets do not inspect Celery or calculate counts from the visible page.

Flet documents mounting into an existing FastAPI app and starting/stopping its app manager with the parent application's lifespan. Integrate that lifecycle with the producer and verify subpath assets and connections. Flet uses a WebSocket for its own UI transport; data refresh still uses ordinary API polling. [Flet FastAPI integration](https://flet.dev/docs/publish/web/dynamic-website/)

```text
ML Platform     Runs | Task types | Monitoring      [Environment v]
Last updated: 2026-09-15 14:30:00 Asia/Manila       [Auto refresh] [Refresh]

Runs
  Workers responding: 2     Running: 1     Queued: 3
  [Expand worker list]
  Failed in selected period: 4     Unretried: 2     [View failures]
  [Up to 5 recent failed rows; each opens task detail]

  [Task name / ID search] [Status v] [Queue v] [Worker v]
  [24 hours v] [From date/time] [To date/time] [Apply]
  Task | ID | Environment | Status | Sent | Finished | Duration | Worker
  ...
  Showing 1–25 of 142                         [25/page v] [Previous] [Next]
```

This wireframe describes layout, not a pixel-perfect reproduction. Use compact tables, readable absolute timestamps, selectable IDs, status text plus color, and expandable long content. A detail panel can take the full page width on smaller screens. Keep long names accessible instead of exposing only an ellipsis.

### Shared environment and refresh behavior

- Selector choices come from code configuration: for example `local`, `staging`, `prod`, plus `All environments`. No create/manage buttons or mutation endpoints. Default to the configured local environment; remember selection within the page session.
- Selection scopes all task rows, failures, cards, graphs, workers, and detail fetches. `All environments` is a read scope; a retry always targets the original task's concrete environment.
- Reset pagination and clear any open detail on environment changes. Preserve environment/time controls when switching tabs. Discard responses from the previous selection, even if they finish later.
- Show the environment on rows when viewing All, and always in details and the retry action. Unknown legacy attribution appears as `Unassigned`; never infer `prod` from missing metadata.
- Poll the visible tab every five seconds; provide manual refresh and pause. Avoid overlapping refreshes and stop polling at session close. Do not tick relative labels or durations every second.
- Show the last **successful** update time. Retain stale data with an error banner on a failed refresh. Separate loading, empty, partial and unavailable states; failure to inspect workers must not erase valid task results.
- Return UTC timestamps; display Asia/Manila initially, with the timezone visible. Convert custom date/time selections to UTC before requests. Duration updates only when the data refreshes.

## 3. Tab behavior

### Runs

1. **Worker summary:** show responding workers, observed running tasks and observed queued tasks. Expand to hostname, environment, consumed queues, active count and observation timestamp. An idle responding worker still appears. A missing inspection reply means `Not responding / unknown`, not proof of worker death. Show partial inspection explicitly; do not call the entire system healthy merely because workers reply.
2. **Failure panel:** show failure total and unretried-failure total for the selected environment and completion window, plus up to five latest failures (name, ID, completion time, short error). Keep it visible even when the main table's status filter is Success. Its label states its scope; table search/queue/worker filters do not silently change it. “View failures” clears those table filters, selects Failure, and uses completion time.
3. **Table:** default last 24 hours plus all observed active tasks, newest sent time first. Columns: task name, task ID, environment, status, queue, sent time, start time, completion time, runtime, worker. MLflow link appears when an actual run reference is available. Show `—` for unknown data.
4. **Filters:** case-insensitive task-name/ID search, exact task type, multiselect status, queue, worker, and custom date/time range. Presets: 1h, 12h, 24h, 72h. Time basis: Activity (default), Sent, Started, Completed. “Include active outside range” is on for Activity by default and explicit in the UI.
5. **Ordering/pagination:** sortable name, status, sent/start/completion time, runtime, worker; page sizes 25/50/100. Filtering and sorting happen before pagination on the server. Clicking a row opens full detail; closing it preserves the table controls and page.

“Active” here includes known submitted, queued, received, started and retry-waiting observations. Redis backend `PENDING` alone does not establish any of these states. [Celery task states](https://docs.celeryq.dev/en/stable/userguide/tasks.html#pending)

### Task detail (shared across tabs)

Show ID, fully qualified name, environment, status, queue, worker, priority, redelivery flag if known, lifecycle timestamps, runtime, Celery automatic retry count, and manual retry parent/child links. Include formatted JSON args/kwargs, successful result, output references and MLflow link when available.

Failures show the error message prominently and a selectable, scrollable traceback preserving line breaks. Use `Traceback unavailable` for null/missing traceback, not a blank box. Render returned text as text, not executable markup. Lists carry short error previews; full inputs, results and traceback are fetched only for detail, with configured size limits and explicit truncation flags.

Offer **Retry with same inputs** only when API eligibility permits it; otherwise show the reason. An accepted retry shows a link to the new task. Do not change the original failure into a success or “resolved” state. Return focus to the triggering row when closing the panel.

### Task types

Inspired by [tasks.png](../tasks.png): one card per `(environment, fully qualified task name)`, including configured types with no observations. All-environments mode keeps environment cards separate rather than blending prod and staging. Search by name; sort by unretried failures descending, then failures descending, then name. Paginate at 24 cards.

Each card shows:

- Task name and environment; latest known execution timestamp.
- Observed active count (all ages) and completed count (selected completion window).
- Success, failure and revoked totals; average terminal runtime with a count of usable runtime samples.
- Small stacked completion chart, using the same bucket rules as Monitoring.
- Prominent `N unretried failures` badge; counts scoped to the selected completion window.

Clicking a card opens a task-type detail view with these totals, larger chart, recent failures and paginated runs constrained to that name/environment. Clicking its badge directly opens the failure subset. Individual rows use the shared task detail. This is a read-only task catalog, not an editor of Python task definitions.

### Monitoring

Start with three panels, all scoped to the environment and selected window:

| Panel | Meaning |
| --- | --- |
| Completed tasks over time | Stacked Success / Failure / Revoked counts by completion time; total is their sum |
| Submitted tasks over time | Count by recorded submission time, with coverage shown; never substitute completions when submission data is absent |
| Average runtime over time | Mean `(completed_at - started_at)` for terminal tasks in each completion bucket; include sample count, null for no valid samples |

The default outcome histogram has exactly 24 rolling one-hour buckets covering the last 24 hours, including empty buckets. Custom ranges use 5m/1h/1d intervals with a maximum of 288 buckets; reject oversized requests rather than silently downsampling. The final bucket may be shorter than its interval. Label exact bounds and units.

Add future panels in Python using an existing API series or an explicitly defined new metric. No user-authored queries or persisted panel layouts. Historical queue depth, worker CPU/memory and active concurrency need sampled measurements; do not reconstruct those curves from today's worker inspection or `count_pending` result alone.

Use native Flet charts for the initial bars/line. Plotly is an optional renderer for later Python-defined figures: verify the pinned Flet chart package and its rendering dependencies in the producer image before selecting it. Do not promise browser Plotly interactions just because a Figure can be displayed. [Flet PlotlyChart](https://docs.flet.dev/charts/plotly_chart/)

## 4. Results API contract

Keep the existing route vocabulary. Add five routes and extend two; avoid copying the reference tool's registry/session/config/event APIs.

| Route | Contract |
| --- | --- |
| `GET /environments` | Read-only configured IDs, labels, queues and default ID; no credentials |
| `GET /workers?environment=...` | Worker items plus observed time, coverage and inspection warnings |
| `GET /tasks` | Paginated run summaries with filtering/ordering described below |
| `GET /tasks/{task_id}?environment=...` | Full task detail, traceback and retry eligibility/links |
| `GET /task-types` | Paginated per-type aggregates and compact completion buckets; optional exact `name` and name search |
| `GET /task-metrics` | Active counts, terminal outcome counts, unretried count and the three bucket series |
| `POST /tasks/{task_id}/retry` | Request a new execution linked to one failed execution |

Existing submission endpoints, `/active`, `/pending`, `/revoke/{task_id}` and `/abort/{task_id}` remain available. The first UI does not need revoke/abort buttons. Apply environment validation to any reused controls; an environment dropdown alone is not routing isolation or authorization.

### Queries, pagination and time

`GET /tasks` parameters:

| Parameter | Proposed behavior |
| --- | --- |
| `environment` | Configured ID, `all`, or `unassigned`; omitted defaults to `all` for existing API callers; UI always sends its selection |
| `name`, `q`, `queue`, `worker` | Exact name/queue/worker; `q` searches name and ID only; predicates combine with AND |
| repeated `status` | `SUBMITTED`, `QUEUED`, `RECEIVED`, `STARTED`, `RETRY`, `SUCCESS`, `FAILURE`, `REVOKED`, `UNKNOWN`; omitted means all observed states |
| `start`, `end` | Timezone-aware ISO 8601; default rolling last 24 hours if both absent; require both when custom |
| `time_field` | `activity` default: sent OR completed within window; alternatives `sent`, `started`, `completed` |
| `include_active` | Default true for Activity, false otherwise; adds observed active rows outside range but still applies other filters |
| `unretried` | Optional boolean restricting failure rows by the definition below |
| `sort`, `order` | `sent_at` default; allowlisted displayed sort fields; `asc` or `desc` (default) |
| `page`, `page_size` | 1-based; default 1 and 25; page size 1–100 |

Intervals are `[start, end)`: start included, end excluded. Validate start < end and reject naive timestamps, unsupported fields and invalid pagination with 422. Tie-break by task ID in the requested sort direction; nulls always last. An out-of-range page returns empty items with the actual total. This is live offset pagination: records can move between pages during execution/refresh. Do not claim snapshot-stable browsing across requests.

Example of the proposed global failure query:

```http
GET /tasks?environment=all&status=FAILURE&start=2026-09-14T06:00:00Z&end=2026-09-15T06:00:00Z&time_field=completed&include_active=false&sort=completed_at&order=desc&page=1&page_size=25
```

List response envelope:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 25,
  "observed_at": "2026-09-15T06:00:00Z",
  "window": {"start": "2026-09-14T06:00:00Z", "end": "2026-09-15T06:00:00Z"},
  "coverage": {"retention_seconds": 259200, "partial": false, "warnings": []}
}
```

For summaries, `/task-types` accepts environment, name/search, window, interval, page/page_size and an allowlisted card sort. `/task-metrics` accepts environment, optional exact name, window and interval. These windows always select **completion** outcomes; submitted-series placement independently uses submission time. Active counts ignore time bounds. Do not apply table status/search/pagination to monitoring totals.

Metrics include `active_counts`, `outcome_counts`, `unretried_failure_count` and `buckets`; each bucket has `start`, `end`, `submitted`, `success`, `failure`, `revoked`, `runtime_mean_seconds`, and `runtime_sample_count`. Every aggregate carries the same window/coverage metadata as lists. Type items add `environment`, `name`, `last_execution_at` and corresponding totals/buckets. Workers carry `hostname`, `environment`, `queues`, `active_count`, `observed_at`, and `inspection_status`; unknown fields are nullable.

Fetch metrics first when establishing a rolling window, then reuse its returned bounds for the tab's other requests. Aggregate over the full matching retained dataset before pagination. Use one materialized set of observations per aggregation response so chart sums match outcome totals. Separate HTTP requests are eventually consistent; a shared window does not make Redis reads transactional.

### Detail and errors

Keep `task_id`, `name`, `status`, `args`, `kwargs`, `queue`, `worker`, `retries`, `date_done`, `result`, and the string `error` where available. Add canonical `submitted_at`, `sent_at`, `received_at`, `started_at`, `completed_at`, `runtime_seconds`, `environment`, `traceback`, `retry_of`, `root_task_id`, `retried_by`, `retry_dispatch_status`, `can_retry`, and `retry_disabled_reason`. Distinguish producer submission time from confirmed publication (`sent_at`). Missing evidence stays null.

Unknown or expired ID: 404 `task_not_found` (without tombstones, these are indistinguishable). Known submission without a backend result: its recorded state, not 404. An ID outside the requested environment also returns 404. Backend outage: 503 `results_unavailable`. Missing optional lifecycle fields: detail remains available with coverage warnings. Use a structured `detail: {code, message}` for new errors.

**Migration:** changing `/tasks` from a bare array to an envelope, replacing `limit`, broadening states, defaulting to a time window and making `end` exclusive are intentional breaking changes to this experimental API. Update OpenAPI, examples and discovered callers together in its implementation checkpoint; do not silently treat old `limit` as ignored (return 422 with migration guidance). Additive detail fields preserve existing names; changing unknown-ID behavior from `PENDING` to 404 must be documented. No runtime behavior changes in this spec-only edit.

## 5. Minimal data additions

Use the existing Redis result backend plus a small platform-owned observation record per task ID. Avoid a new database or event-stream service for this UI. A result-key scan alone cannot discover submitted or queued tasks, and worker inspection alone cannot reconstruct history.

- Record environment, task name, original JSON args/kwargs, code contract version, queue, priority and submission timestamp **before** producer publication. Attach environment metadata to messages. Worker lifecycle updates merge into the same record; Beat also supplies explicit environment/routing metadata. Never trust the UI to supply an arbitrary broker URL or task name.
- Treat the code environment registry as the queue/worker mapping authority. Retain environment explicitly on each record. Permit legacy attribution only from an exact configured queue/worker mapping; otherwise use Unassigned. Prefix parsing is not sufficient evidence.
- Keep terminal backend metadata authoritative for final execution outcome. Observations supply earlier states and missing context. Late sent/received updates cannot regress a known terminal state. Within one ID, `RETRY` can return to `STARTED`; record that it is another attempt rather than inventing a terminal failure.
- Use `UNKNOWN` with a reason when dispatch or execution state cannot be established; a stale STARTED observation is not proof that a process is still running. Show live worker evidence separately. Automatic stale-job repair remains milestone 3.
- Initially scan the small retained dataset once per query-service refresh, merge by task ID and reuse the result for five seconds. All list/aggregate routes use this service; no separate per-card scan and no keys-per-row Redis connection creation. Invalidate on accepted retry. Measure scan cost before introducing secondary indexes.
- Coverage includes missing/expired metadata, unsupported historical periods and failed optional reads. If a scan/read budget is exceeded, return partial coverage or 503; never label a truncated count exact. Retention is three days of retained observations, not an all-time total. Zero means a measured empty bucket; unavailable history is marked missing.
- Give terminal observation records the three-day retention period from completion. Keep known active records available beyond the chart window; their cleanup policy must not silently drop long-running jobs. Existing signal hashes/results remain best-effort and have independently refreshed TTLs. Retain retry links/admission records for as long as the associated observable chain remains actionable.
- Limit result/traceback sizes and redact configured sensitive fields before exposure. Retry uses separately retained replayable JSON, not truncated or redacted display strings. A type with non-replayable inputs is ineligible.

This record improves observability; it does not make publication atomic with Redis metadata or recover a killed worker. Migrating to the planned PostgreSQL job catalog later should preserve UI/query contracts where practical and explicitly migrate any changed semantics.

## 6. On-demand retry

### Meaning

Manual retry creates a **new task ID** with the original allowlisted task name, validated inputs, environment, queue and priority. Set `retry_of` to the failed ID and `root_task_id` to the first ID in the manual chain. The original remains FAILURE. Do not replay stale ETA/expiry, callbacks, chains or arbitrary task headers.

Celery's in-task `retry()` reuses the task ID; the backend retry counter therefore describes a different mechanism from this manual rerun. Display automatic retry count separately. [Celery retry behavior](https://docs.celeryq.dev/en/stable/userguide/tasks.html#retrying)

An **unretried failure** is a retained FAILURE with no accepted manual retry child. A request whose dispatch is uncertain is shown separately as `Retry dispatch unknown`; it is not labeled unretried or resolved. In A → B → C, with A and B failed and C successful, A/B remain historical failures but neither is unretried. If C fails, C contributes one unretried failure. Legacy records without tracked lineage show `Retry history unknown`, not a confident unretried badge.

Observability counts use **one Celery task ID as one execution**: manual retry adds another execution; automatic retry within that ID contributes only its final outcome. Thus two failures followed by one successful manual retry remain two failures and one success in the completion chart. The future durable-job dashboard groups attempts under a logical job; its original milestone worksheet's one-final-outcome-per-job rule still applies there. Label this Redis UI's metric unit as executions rather than claiming both are the same metric.

### Request and response

```http
POST /tasks/failed-id/retry
Idempotency-Key: <client-generated UUID retained for repeated clicks/network retries>
Content-Type: application/json

{"environment": "staging"}
```

```json
{
  "task_id": "new-id",
  "retry_of": "failed-id",
  "root_task_id": "failed-id",
  "environment": "staging",
  "dispatch_status": "published"
}
```

Return 202 when dispatch is accepted/attempted, with `Location: /tasks/new-id`. The detail also reports dispatch state. Never imply task success or exactly-once execution.

Eligibility: terminal FAILURE, known concrete environment, replayable inputs, enabled task contract with current validation, and no existing child or in-flight retry request. Code registration controls `manual_retry_allowed`; leave it false for tasks whose side effects are unsafe to repeat. Existing revoke/abort endpoints do not establish retry eligibility.

Errors: 404 unknown/out-of-scope task; 409 ineligible state, existing child, uncertain prior dispatch or incompatible task contract; 422 malformed request/key; 503 unavailable prerequisites before dispatch. Return machine-readable reasons used by the button's disabled state. The server rechecks eligibility at click time.

### Double clicks and publication failures

Before sending, atomically reserve one child ID and the idempotency key against the parent in Redis. Concurrent requests with the same key return the same child; a different key cannot create a sibling retry. Reusing a key for another parent/environment conflicts. Permit retrying a subsequently failed child to extend the chain.

Persist replay data and dispatch intent before calling Celery. If publication is known successful, record `published`. If the broker call or producer crashes after sending may have begun, retain the child and mark/infer `unknown`; return the same child on a repeated request and do **not** blindly send again. Worker evidence can establish that this child executed. A stale dispatch intent is unknown, not proof publication failed. Disable automatic producer publish retries for this manual dispatch path until their duplicate behavior is covered by the tests.

The first retry module may deliberately leave ambiguous dispatch requiring investigation; display that state and block another retry from the same parent. This is the small, honest failure boundary. Durable resend/reconciliation belongs with the planned outbox/attempt module. A retry admission guard prevents duplicate UI submissions, not every possible broker redelivery or repeated side effect.

## 7. Implementation modules and acceptance expectations

This is a specification and sequencing outline, not a replacement implementation worksheet. Expand one selected module against the code before implementing it; leave mechanisms as learner work. Flet/chart packages must be pinned and verified with Python 3.13 and the producer image at that point. Local work needs Redis, producer and workers via Compose; no additional paid service/account is required.

| Module | Files/boundary to develop | Required evidence |
| --- | --- | --- |
| A. Results contract and observations | `producer.py`, proposed `results.py` and `schemas.py`, `task_events.py` | Global failures, detail traceback, pagination, temporal rules, state precedence, TTL/coverage and unknown-ID behavior |
| B. Environment and workers | Proposed `environments.py`, producer/Beat publication and worker config, Compose | Two environments, exact routing/attribution, idle worker visible, partial/no replies distinguishable from zero running tasks |
| C. Aggregation | Proposed `observability.py`, Results routes | Totals independent of pagination; per-type groups, empty buckets, boundary timestamps, missing durations, manual-vs-automatic retry counting |
| D. Producer-hosted UI | Proposed `ui.py`, `ui_state.py`, producer lifespan/dependencies | Runs first with minimum counts/histogram, then Task types and Monitoring; real browser mount, chart and state checks |
| E. Manual retry | Proposed `retry_service.py`, submission helper, detail UI | Validation, new ID and lineage, concurrency/idempotency, publication ambiguity and preservation of original error |

Expected behavioral cases (test files to create during implementation, not existing passing tests):

- `test_results_api.py`: no name filter returns failed `one_over` and another task type; page totals cover more than one page; equal timestamps sort deterministically; start included/end excluded; invalid inputs rejected; unknown task 404 and backend failure 503.
- `test_task_observations.py`: pre-result submission appears; late sent signal cannot overwrite success; repeated lifecycle events do not multiply executions; missing timestamps/legacy attribution/expiry remain explicit; active records survive the history window.
- `test_environments.py` and `test_workers_api.py`: identical task names in staging/prod stay separate; all scopes do not hide Unassigned; retry cannot change environment; idle responding workers appear; failed inspection is unavailable/partial, not zero.
- `test_observability.py`: 24 one-hour bins including empty bins; completion at start/end; equivalent UTC offsets; no chart/count drift within one response; missing runtime excluded from mean; unavailable coverage differs from empty data; type cards include zero-observation configured types.
- `test_ui_state.py`: loading/empty/success/stale/recovery; environment-switch race; pause, no overlapping polling and cancellation on close; failure panel remains visible with a Success table filter; detail fetches traceback; preserve filters on close.
- `test_retry_api.py`: original FAILURE preserved; new task reuses inputs/queue/priority/environment; disabled/unknown contracts rejected; same-key double click and different-key concurrency create at most one child; timeout/crash retains unknown dispatch and does not republish; a failed child becomes the next unretried failure.
- Producer integration: `/ui/`, UI assets and Flet connection load alongside `/docs`, `/health` and task routes; lifecycle shutdown is clean. Browser-check table scrolling, absolute timestamps, readable traceback, chart labels and environment switching.

Integrated exercise: run a successful add, failing `one_over(0)`, and slow wait in each of two configured environments. Confirm worker/active observations, exact failure filters and per-type cards; inspect the error and traceback; retry one failure and observe a new linked failure with the same input. Pause/restore a dependency to demonstrate stale data. Use timestamp fixtures for chart boundaries rather than waiting an hour. Record actual commands/results and limitations in milestone 1's notes when the modules are implemented.

## 8. Reference decisions

The supplied screenshots ground the product scope: [environment selector](../environment_toggle.png), [full table](../full_table.png), [task cards](../tasks.png), and [API examples 1](../api1.png), [2](../api2.png), [3](../api3.png). They are examples of desired interactions, not evidence of the current platform's capabilities.

Chosen defaults for review: Runs / Task types / Monitoring labels; Asia/Manila display; three-day retained history; five-second polling; code-configured environments and panels; manual retry with unchanged inputs and a new ID. The substantive implementation decision still to validate is Flet/chart package compatibility in the producer image. Longer history, richer retry recovery, and infrastructure metrics require separately scoped work.
