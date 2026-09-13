# Build worksheets

Each worksheet develops one platform milestone through small modules. You implement a mechanism, inspect it, and make its tests pass before adding the next part. The application accumulates in the repository; completing a worksheet does not create a disconnected tutorial app.

Each worksheet provides a concrete outcome, prerequisites, explanations, proposed file layout, incomplete interfaces, a bounded build sequence, behavioral tests, and evidence you can inspect. Worksheets deliberately build on the preceding platform code. No external course material or private repository is needed; required background is stated locally, and technical references point to public documentation.

Use Markdown instructions, ordinary Python source files, terminal commands, Docker Compose, and pytest. Jupyter notebooks are optional scratch space for an experiment; no worksheet requires them.

The [architecture spec](../specs/README.md) describes the destination. Milestone 1 has a detailed worksheet and is the next implementation step. Milestones 2 and 3 have orientation sketches so early choices have context. Expand those sketches against the actual code and evidence from preceding work before implementing them; milestones 4–6 remain roadmap entries.

A sketch records the intended outcome, likely modules, learning goals, expected tests, and unresolved decisions. A detailed worksheet adds concrete interfaces, migrations, configuration, and runnable test instructions. Keep these preparation states separate from implementation status: neither means the milestone's code or tests are complete. Refine milestone 1 one module at a time as you work, rather than trying to settle every future detail before starting.

| Milestone | Deliverable | Worksheet status | Final test checkpoint |
| --- | --- | --- | --- |
| [1. Local system and minimal dashboard](milestone-01/README.md) | Submit and run jobs, track a model in MLflow, see the jobs table, status counts, and 24-hour histogram | Ready to work through; seven modules | Unit, local integration, and end-to-end tests, plus dashboard inspection |
| [2. Azure transport experiment](milestone-02/README.md) | Check the pinned Celery/Kombu/Service Bus combination using the local task contracts | Orientation sketch; expand after milestone 1 | Real Azure routing, result retrieval, long-task lock behavior, and worker-failure tests |
| [3. Durable orchestration](milestone-03/README.md) | Harden publication and attempt ownership; add recovery, persistent Beat schedules, and batches | Orientation sketch; expand after the transport decision | Broker outage, duplicate delivery, stale worker, scheduler restart, and batch tests |
| 4. Expanded team workflows | Extend the dashboard; add registry operations and an inference endpoint | Write against milestone 3 | Schedule/batch views, model selection, readiness, prediction, and return-to-previous-version tests |
| 5. Terraform development deployment | Reproduce the environment with documented resources, identities, and scaling | Write against the validated app | Terraform checks and deployed integration/scaling tests |
| 6. Operational readiness | Exercise restore, redeployment, retention, and measured service limits | Write against the deployed environment | Restore/redeployment tests and explicitly defined performance checks |

For the transport experiment, a failed compatibility requirement is a useful result. It means the proposed combination has not passed; document the failure and revise the decision rather than skipping the test or calling the milestone complete.

Use this working loop for each module:

1. Read its concrete example and describe the expected behavior in your own words.
2. Create the named interfaces and the first behavioral test. Confirm an unfinished implementation fails for the expected reason.
3. Implement one small part, using AI for explanation, review, or a selected function when useful.
4. Run the module's tests and the relevant tests from earlier modules. Inspect the artifact or service response.
5. Record the commands, results, one thing you can now explain, and any remaining limitation.

A useful AI request is: “Work with me on milestone 1, module C. Explain the database transaction around submission. Help me write the failing API test first; keep implementation help to this module.” You can request larger or smaller units explicitly. No recurring approval ritual is needed within the unit you selected.

All commands and source trees in a worksheet describe files to create during that worksheet. They are not a claim that the repository already runs. Tests are also implementation work: the worksheet specifies their cases and expected results, and you or an assistant write them at the relevant checkpoint.

For every later worksheet, include a concrete walkthrough, the required prior modules, unfamiliar concepts explained in context, scope and deferred behavior, interface contracts, small numbered steps, exact target test commands, expected assertions, a failure exercise, and space for results. Keep cloud costs and required accounts explicit when Azure enters the work.

Track completed modules and observations in a `NOTES.md` next to that milestone's README. Record actual commands and pass/fail counts after running them. A milestone is complete when its required tests pass and its end-to-end behavior has been inspected; documentation-only preparation does not satisfy that checkpoint.
