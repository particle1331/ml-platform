# Milestone 3 — Recover interrupted jobs and run durable schedules

[Worksheet sequence](../README.md) · [Previous: Azure transport](../milestone-02/README.md) · [Architecture spec](../../specs/README.md)

**Status: orientation sketch.** Expand the interfaces, migrations, configuration, and module commands against the implemented local system and milestone 2's transport decision. The tests described here are targets, not existing or passing tests.

You will interrupt a worker during a job, start a replacement, and watch the job finish without accepting a stale worker's result. Then you will restart the scheduler and confirm that its schedule survives and that one scheduled occurrence creates one logical job. Finally, submit a small batch and verify its aggregate status as individual jobs finish or fail.

The first action is to reproduce milestone 1's known limitation: kill a worker after its job becomes `RUNNING` and observe the stuck record. Save its job ID and timeline. That example creates the need for an expiring execution claim instead of adding recovery mechanisms without observing the problem.

Prerequisites are milestone 1's passing suite and milestone 2's documented transport decision. Most development uses the local PostgreSQL/RabbitMQ/Azurite environment. Repeat the relevant transport/recovery tests against the selected cloud broker before claiming cloud behavior. Local work needs no new cloud services; Azure validation uses the bounded experiment environment and current cost estimates from milestone 2.

A **job** is the logical request. An **attempt** is one execution of that request; retries can create several attempts. A **lease** is a claim that expires unless renewed. A worker sends **heartbeats**, or periodic still-alive updates, to renew its attempt. A replacement attempt gets a new token, and the database rejects writes from the old token. That ownership check is sometimes called **fencing**.

An application lease and a Service Bus message lock solve different problems. The broker decides when to redeliver a message; the platform decides which attempt may update the logical job or publish its accepted result. Redelivery alone does not repair a `RUNNING` row, and a database lease alone does not keep a broker lock alive.

| Module | What you will add or inspect | Expected checkpoint |
| --- | --- | --- |
| A. Separate jobs from attempts | Attempt records, attempt tokens, expiry, heartbeats, and atomic ownership checks | Concurrent claims have one current owner; expired tokens cannot heartbeat or complete a job |
| B. Recover submission and execution | Concurrent-safe outbox publication, retry policy, and a reconciliation loop that revisits stale records | Broker outages, duplicate publication, worker death, and retry exhaustion produce the defined durable outcomes |
| C. Make output acceptance safe | Attempt-specific artifact paths and an atomic database choice of the accepted result | A late attempt cannot overwrite the selected result or create a second accepted logical effect |
| D. Persist and coordinate Beat | Schedule definitions, occurrence records, database-backed scheduler state, and single active scheduling ownership | Schedule restart and overlapping scheduler processes do not create duplicate logical occurrences |
| E. Define schedule policy and batches | Missed-run/overlap rules, batch membership, and aggregate status | Deterministic time-based tests and mixed-outcome batch counts pass |
| F. Exercise the integrated system | A repeatable failure harness, migrations, and updated job-status reporting | Local failure/recovery tests pass; selected Azure cases reproduce the required behavior |

For A, propose service operations to claim an attempt, heartbeat with its token, and finish with that token. Completion must check both current ownership and valid lease according to a consistent database time. Use controllable time in unit tests and real concurrent PostgreSQL transactions in integration tests. A worker whose lease expired must not regain authority just because it later reconnects.

For B, the **reconciler** is a small process that periodically compares stored state with what should happen next. It finds expired attempts and incomplete publication, then creates or schedules the next bounded action. Choose one authoritative application retry policy. Distinguish it from broker redelivery and SDK network retries so independently nested retries do not multiply executions without a bound. State which failures are retryable, maximum attempts, retry delays, and the terminal outcome on exhaustion.

Keep a record of each publication intent rather than assuming milestone 1's one-outbox-row-per-job shape can represent every retry. Decide when redelivery reuses an attempt and when recovery creates a new one. This is a design question to settle while expanding B, using milestone 2's measurements.

For C, use a small observable effect: each attempt uploads an evaluation file under its own path, but only the current owner can atomically select the job's accepted output reference. Duplicate execution may leave extra files or MLflow runs; record and eventually clean them up. Do not equate one accepted result with exactly-once execution or claim that a database token can undo arbitrary external side effects. Extend the policy explicitly before jobs send messages or mutate other systems.

For D, Celery Beat remains its own small process using shared submission code. Select or implement its PostgreSQL-backed schedule integration after inspecting maintained options and their compatibility with the actual application. Beat's default local-file persistence does not implement the target database design, and Celery requires a single active scheduler for a schedule. [Celery periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)

Each schedule occurrence has a stable identity such as `(schedule_id, scheduled_for)`. Save the occurrence, job, and outbox entry in one transaction. Combine unique occurrence constraints with scheduler ownership: the unique constraint protects logical insertion, while ownership controls who advances the schedule. Test a scheduler that loses its ownership during a pause and later resumes. A configured replica count of one does not by itself test overlapping deployments.

Initial schedule policies from the architecture remain proposals to encode and test: persist UTC times, display the selected timezone, prevent overlapping training runs, and coalesce missed occurrences into one run after downtime. Specify what “coalesce” selects, whether retries count as an active run, and what happens when a schedule is disabled or edited near its next due time. Retain enough occurrence history to explain skipped or combined work.

For E, a batch groups logical jobs. Define membership and expected job count when creating it, then aggregate terminal outcomes and unfinished work. A batch is finished only when all its children are terminal; report failures separately rather than labeling a partially failed batch successful. Count final jobs, not attempt records. Keep changes to the existing dashboard limited to truthful status mapping and counts; dedicated schedule/batch management views remain milestone 4.

Suggested additions and modifications, to refine while expanding:

```text
src/ml_platform/store.py             # transactional attempt and occurrence writes
src/ml_platform/worker.py            # heartbeat and attempt-token reporting
src/ml_platform/publisher.py         # retry-safe publication records
src/ml_platform/reconcile.py
src/ml_platform/scheduler.py         # Beat integration
src/ml_platform/batches.py
migrations/                         # migrate existing jobs without losing history
tests/unit/test_retry_policy.py
tests/unit/test_schedule_policy.py
tests/integration/test_attempts.py
tests/integration/test_schedules.py
tests/integration/test_batches.py
tests/host/test_recovery.py          # control real worker/scheduler processes
docs/worksheets/milestone-03/NOTES.md
```

Proposed test targets, requiring the same explicit isolation and service setup as milestone 1:

```bash
uv run pytest tests/unit/test_retry_policy.py tests/unit/test_schedule_policy.py -q
uv run pytest tests/integration/test_attempts.py tests/integration/test_schedules.py tests/integration/test_batches.py -q
uv run pytest tests/host/test_recovery.py -q
```

The completed worksheet must assign these tests to module checkpoints and specify their fixtures, time control, process startup, and deadlines. Cover these concrete cases:

- Crash after publication but before its database confirmation: publication can repeat, but the logical job and accepted effect remain unique.
- Kill the worker before output upload; let its lease expire; a new attempt finishes according to policy.
- Kill the worker after output upload but before completion; recovery never confuses an unaccepted artifact with a committed result.
- Pause a worker until a replacement owns the job, then resume it; the old worker's heartbeat and completion are rejected.
- Exhaust retries; the job reaches a terminal failure rather than looping or staying running forever. Broker dead-lettered messages—deliveries moved aside after repeated delivery problems—must be surfaced and reconciled rather than silently ignored.
- Run two schedulers over the same due time, then restart the owner; one logical occurrence/job remains, with a correct next due time.
- Simulate scheduler downtime and a still-running prior training job; coalescing and overlap rules match the specified policy without waiting hours in tests.
- Finish a batch with mixed outcomes; counts sum to membership and the batch remains unfinished while any child is active.
- Apply migrations to milestone 1 data; previous job history, output references, and dashboard totals remain interpretable.

At the final integrated checkpoint, submit an ad hoc job, a periodic job, and a batch; interrupt selected processes; verify eventual outcomes, attempt history, schedule history, and the existing dashboard. Record the same job's timeline from submission through recovery. Keep assertions separate for accepted jobs, execution attempts, and accepted effects.

Before implementation, resolve the chosen broker's redelivery/acknowledgement behavior, retry ownership, lease/heartbeat timings, Beat integration, occurrence rules, and accepted-output commit boundary. Preserve these as explicit decisions in the worksheet rather than silently building them into code. Completion requires passing the required tests; a sketch or a successful happy-path demo does not establish durable recovery.
